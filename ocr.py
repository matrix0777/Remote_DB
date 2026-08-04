import os
from typing import List
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
import fitz  # PyMuPDF
from google import genai
from google.genai import types

# Load environment variables from .env file
load_dotenv()

app = FastAPI(
    title="AI Medical Form Automation Pipeline (Gemini Edition)",
    description="Automated medical form filling using structured medical records and Gemini 2.5 Flash structured outputs.",
    version="1.0.0"
)

# Initialize Google GenAI Client
# (Reads GEMINI_API_KEY loaded into os.environ by dotenv)
gemini_api_key = os.getenv("GEMINI_API_KEY")
if not gemini_api_key:
    raise RuntimeError("GEMINI_API_KEY not found in environment variables or .env file.")

client = genai.Client(api_key=gemini_api_key)


# ==========================================
# 1. Pydantic Schemas for Strict Extraction
# ==========================================

class ExtractedField(BaseModel):
    field_name: str = Field(description="The exact name or label of the form field being answered.")
    value: str = Field(description="The extracted answer based strictly on the medical records.")
    confidence_score: float = Field(description="Confidence score between 0.0 and 1.0 for this extraction.")
    source_evidence: str = Field(description="Direct verbatim quote or section reference from the medical records.")


class MedicalFormExtraction(BaseModel):
    fields: List[ExtractedField] = Field(description="List of extracted fields with values and evidence.")
    overall_confidence: float = Field(description="Average confidence score across all fields.")
    requires_manual_review: bool = Field(description="True if confidence is below 0.85 or key data is uncertain.")


class FormProcessResponse(BaseModel):
    status: str
    output_pdf_path: str
    extraction_details: MedicalFormExtraction


# ==========================================
# 2. Core Gemini Extraction Engine
# ==========================================

def extract_form_data(medical_records_text: str, form_schema_description: str) -> MedicalFormExtraction:
    """
    Uses Gemini native structured outputs to extract fields, confidence scores, and evidence matching the Pydantic schema.
    """
    system_prompt = (
        "You are an expert clinical data extraction assistant. "
        "Your task is to accurately extract information from structured medical records "
        "to answer specific medical form requirements. "
        "Provide a confidence score and direct source quote for every field extracted."
    )

    user_prompt = f"""
    MEDICAL RECORDS SOURCE OF TRUTH:
    {medical_records_text}

    TARGET FORM FIELDS / REQUIREMENTS:
    {form_schema_description}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=MedicalFormExtraction,
                temperature=0.1,
            ),
        )

        if response.parsed:
            return response.parsed
        else:
            return MedicalFormExtraction.model_validate_json(response.text)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini Extraction failed: {str(e)}")


# ==========================================
# 3. PDF Manipulation & Form Filling Engine
# ==========================================

def fill_pdf_form(pdf_path: str, extraction_data: MedicalFormExtraction, output_path: str) -> str:
    """
    Fills interactive AcroForm fields if available, otherwise draws text at fallback coordinates.
    """
    doc = fitz.open(pdf_path)
    form_filled = False

    # Attempt to populate interactive form fields (AcroForm widgets)
    for page in doc:
        widgets = page.widgets()
        if widgets:
            form_filled = True
            for widget in widgets:
                field_name = widget.field_name
                match = next((f for f in extraction_data.fields if f.field_name.lower() in field_name.lower()), None)
                if match:
                    widget.field_value = match.value
                    widget.update()

    # If the PDF is flat (non-fillable / scanned), apply text summary stamping
    if not form_filled:
        page = doc[0]
        rect = fitz.Rect(50, 50, 550, 200)
        annot_text = "AI-Generated Draft Summary (Gemini):\n" + "\n".join(
            [f"- {f.field_name}: {f.value}" for f in extraction_data.fields[:5]])
        page.insert_textbox(rect, annot_text, fontsize=9, color=(0, 0, 0))

    doc.save(output_path)
    doc.close()
    return output_path


# ==========================================
# 4. API Endpoints
# ==========================================

@app.post("/process-form/", response_model=FormProcessResponse)
async def process_medical_form(
        medical_records: UploadFile = File(..., description="Text or JSON file containing structured medical records"),
        blank_form_pdf: UploadFile = File(..., description="The blank medical form PDF template"),
        form_schema_description: str = Form(..., description="Description or list of fields required by the form")
):
    """
    Ingests medical records and a blank PDF, extracts data via Gemini using Pydantic schemas,
    and returns a completed PDF draft ready for human review.
    """
    records_content = await medical_records.read()
    try:
        records_text = records_content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Medical records file must be valid UTF-8 text or JSON.")

    temp_pdf_path = f"temp_{blank_form_pdf.filename}"
    output_pdf_path = f"completed_{blank_form_pdf.filename}"

    with open(temp_pdf_path, "wb") as buffer:
        buffer.write(await blank_form_pdf.read())

    try:
        extraction_result = extract_form_data(records_text, form_schema_description)
        fill_pdf_form(temp_pdf_path, extraction_result, output_pdf_path)

    finally:
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

    return FormProcessResponse(
        status="success",
        output_pdf_path=output_pdf_path,
        extraction_details=extraction_result
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)