-- 1. USERS & TEAMS
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'manager', 'member') DEFAULT 'member',
    timezone VARCHAR(50) DEFAULT 'UTC',
    skills VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE teams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    created_by INT,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE team_members (
    team_id INT,
    user_id INT,
    PRIMARY KEY (team_id, user_id),
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 2. PROJECTS, SPRINTS & TASKS
CREATE TABLE projects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    status ENUM('Planning', 'Active', 'Completed') DEFAULT 'Planning',
    budget DECIMAL(10,2) DEFAULT 0.00,
    team_id INT,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE TABLE sprints (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    start_date DATE,
    end_date DATE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sprint_id INT,
    project_id INT NOT NULL,
    title VARCHAR(150) NOT NULL,
    status ENUM('todo', 'in-progress', 'review', 'done') DEFAULT 'todo',
    priority ENUM('low', 'medium', 'high', 'urgent') DEFAULT 'medium',
    assigned_to INT,
    due_date DATETIME,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL,
    FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL
);

-- 3. TIME TRACKING & AUDIT LOGS
CREATE TABLE work_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id INT NOT NULL,
    user_id INT NOT NULL,
    clock_in DATETIME NOT NULL,
    clock_out DATETIME,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE activity_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    action VARCHAR(255) NOT NULL,
    entity_type VARCHAR(50),
    entity_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    message VARCHAR(255) NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 4. MEETINGS & CONFLICT DETECTION
CREATE TABLE meetings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(100) NOT NULL,
    project_id INT,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE meeting_attendees (
    meeting_id INT,
    user_id INT,
    PRIMARY KEY (meeting_id, user_id),
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Indexing for performance
CREATE INDEX idx_tasks_assigned_status ON tasks(assigned_to, status);
CREATE INDEX idx_tasks_due_date ON tasks(due_date);

















--------------------------------------------------------------------------------------






-- TRIGGER: Audit log + Notification on Task Assignment/Status Update
DELIMITER //
CREATE TRIGGER trg_after_task_update
AFTER UPDATE ON tasks
FOR EACH ROW
BEGIN
    IF OLD.status <> NEW.status THEN
        INSERT INTO activity_logs (user_id, action, entity_type, entity_id)
        VALUES (NEW.assigned_to, CONCAT('Changed status from ', OLD.status, ' to ', NEW.status), 'task', NEW.id);
    END IF;

    IF (OLD.assigned_to IS NULL AND NEW.assigned_to IS NOT NULL) OR (OLD.assigned_to <> NEW.assigned_to) THEN
        INSERT INTO notifications (user_id, message)
        VALUES (NEW.assigned_to, CONCAT('You have been assigned to task: ', NEW.title));
    END IF;
END //
DELIMITER ;

-- VIEW: Overdue Tasks Summary
CREATE VIEW v_overdue_tasks AS
SELECT t.id, t.title, t.due_date, u.username AS assigned_user, p.name AS project_name
FROM tasks t
LEFT JOIN users u ON t.assigned_to = u.id
JOIN projects p ON t.project_id = p.id
WHERE t.due_date < NOW() AND t.status <> 'done';

-- VIEW: Workload Distribution
CREATE VIEW v_team_workload AS
SELECT u.id AS user_id, u.username, COUNT(t.id) AS active_tasks
FROM users u
LEFT JOIN tasks t ON u.id = t.assigned_to AND t.status IN ('todo', 'in-progress', 'review')
GROUP BY u.id, u.username;

-- STORED PROCEDURE WITH TRANSACTION: Atomic Task Reassignment
DELIMITER //
CREATE PROCEDURE sp_reassign_task(IN p_task_id INT, IN p_new_user_id INT, IN p_actor_id INT)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
    END;

    START TRANSACTION;
        UPDATE tasks SET assigned_to = p_new_user_id WHERE id = p_task_id;

        INSERT INTO activity_logs (user_id, action, entity_type, entity_id)
        VALUES (p_actor_id, CONCAT('Reassigned task #', p_task_id, ' to user #', p_new_user_id), 'task', p_task_id);

        INSERT INTO notifications (user_id, message)
        VALUES (p_new_user_id, CONCAT('Task #', p_task_id, ' has been reassigned to you.'));
    COMMIT;
END //
DELIMITER ;



-----------------------------------------------------------------------------------------------------


-- Add users
INSERT INTO users (username, hashed_password, role, timezone, skills) VALUES
('alice_admin', 'scrypt_hash_123', 'admin', 'UTC', 'Python, FastAPI, SQL'),
('bob_dev', 'scrypt_hash_456', 'member', 'EST', 'React, CSS');

-- Add team and link members
INSERT INTO teams (name, created_by) VALUES ('Core Engineering', 1);
INSERT INTO team_members (team_id, user_id) VALUES (1, 1), (1, 2);

-- Add project and tasks
INSERT INTO projects (name, status, budget, team_id) VALUES
('AI Enterprise Workspace', 'Active', 50000.00, 1);

INSERT INTO tasks (project_id, title, status, priority, assigned_to, due_date) VALUES
(1, 'Setup DB Triggers', 'done', 'high', 1, '2026-07-30 10:00:00'),
(1, 'Build FastAPI Endpoints', 'in-progress', 'high', 2, '2026-08-01 12:00:00'),
(1, 'Design UI Dashboard', 'todo', 'medium', 2, '2026-08-10 17:00:00');



-------------------------------------------------------------------------------------------------


SELECT * FROM v_team_workload;
SELECT * FROM v_overdue_tasks;



---------------------------------------------------------------------------------------------------


UPDATE tasks SET status = 'review', assigned_to = 1 WHERE id = 2;

-- Check if trigger inserted records automatically:
SELECT * FROM activity_logs;
SELECT * FROM notifications;



-----------------------------------------------------------------------------------------------------


CALL sp_reassign_task(3, 1, 2);




SELECT DATABASE();