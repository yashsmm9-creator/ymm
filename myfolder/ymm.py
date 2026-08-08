TEACHER_ACCESS_CODE = "1O0712M1"

from flask import Flask, render_template, request, redirect, session, url_for
from datetime import datetime

import sqlite3
import os

app = Flask(__name__)
app.secret_key = "secret123"

DB_NAME = "database.db"


# ================= DATABASE =================
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Drop and recreate tables to ensure clean schema
    cur.execute("DROP TABLE IF EXISTS votes")
    cur.execute("DROP TABLE IF EXISTS candidates")
    cur.execute("DROP TABLE IF EXISTS students")
    cur.execute("DROP TABLE IF EXISTS teachers")
    cur.execute("DROP TABLE IF EXISTS election_settings")

    # Recreate all tables with updated schema
    cur.execute("""
    CREATE TABLE teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        division TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        prn TEXT UNIQUE NOT NULL,
        division TEXT,
        year TEXT,
        email TEXT,
        password TEXT NOT NULL,
        gender TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        division TEXT NOT NULL,
        gender TEXT
    )
    """)

    cur.execute("""
CREATE TABLE votes (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   student_id INTEGER,
   category TEXT,
   candidate_id INTEGER,
   division TEXT,
   UNIQUE(student_id, category),
   FOREIGN KEY(student_id) REFERENCES students(id),
   FOREIGN KEY(candidate_id) REFERENCES candidates(id)
)
""")


    # Division-specific election settings
    cur.execute("""
    CREATE TABLE election_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        division TEXT NOT NULL UNIQUE,
        deadline TEXT,
        is_active BOOLEAN DEFAULT 1
    )
    """)

    conn.commit()
    conn.close()


# ================= DATABASE MIGRATION =================
def migrate_db():
    conn = get_db()
    cur = conn.cursor()

    # Check if students table exists
    cur.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='students'
    """)
    table_exists = cur.fetchone()

    # If table doesn't exist, create full DB
    if not table_exists:
        print("Tables not found. Initializing database...")
        conn.close()
        init_db()
        return

    # ---- SAFE MIGRATION ----
    try:
        # Students table
        cur.execute("PRAGMA table_info(students)")
        columns = [col[1] for col in cur.fetchall()]
        if "gender" not in columns:
            cur.execute("ALTER TABLE students ADD COLUMN gender TEXT")
            print("Added gender to students")

        # Candidates table
        cur.execute("PRAGMA table_info(candidates)")
        columns = [col[1] for col in cur.fetchall()]
        if "gender" not in columns:
            cur.execute("ALTER TABLE candidates ADD COLUMN gender TEXT")
            print("Added gender to candidates")

        conn.commit()
    except Exception as e:
        print("Migration failed:", e)
    finally:
        conn.close()



# ================= HOME =================
@app.route("/")
def home():
    return render_template("home.html")


# ================= TEACHER SIGNUP =================
@app.route("/teacher_signup", methods=["GET", "POST"])
def teacher_signup():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        division = request.form["division"]
        access_code = request.form["access_code"]

        # Check Teacher Access Code
        if access_code != TEACHER_ACCESS_CODE:
            return "❌ Invalid Teacher Access Code"

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO teachers (name, email, password, division) VALUES (?, ?, ?, ?)",
                (name, email, password, division)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "Teacher already exists"

        conn.close()
        return redirect(url_for("teacher_login"))

    return render_template("teacher_signup.html")


# ================= TEACHER LOGIN =================
@app.route("/teacher_login", methods=["GET", "POST"])
def teacher_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db()
        teacher = conn.execute(
            "SELECT * FROM teachers WHERE email=? AND password=?",
            (email, password)
        ).fetchone()
        conn.close()

        if teacher:
            session["teacher_id"] = teacher["id"]
            session["teacher_division"] = teacher["division"]
            return redirect(url_for("teacher_dashboard"))

        return "Invalid Email or Password"

    return render_template("teacher_login.html")


# ================= TEACHER DASHBOARD =================
@app.route("/teacher_dashboard")
def teacher_dashboard():
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))

    conn = get_db()

    # Get teacher division
    teacher = conn.execute(
        "SELECT division FROM teachers WHERE id=?",
        (session["teacher_id"],)
    ).fetchone()

    if not teacher:
        conn.close()
        session.clear()
        return redirect(url_for("teacher_login"))

    teacher_division = teacher["division"]

    # Count candidates of this division by category
    boys_rep_count = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE division=? AND category='boys_representative'",
        (teacher_division,)
    ).fetchone()[0]
    
    girls_rep_count = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE division=? AND category='girls_representative'",
        (teacher_division,)
    ).fetchone()[0]

    # Fetch division-specific settings
    setting = conn.execute(
        "SELECT deadline, is_active FROM election_settings WHERE division=?",
        (teacher_division,)
    ).fetchone()

    # Create default setting if not exists
    if not setting:
        conn.execute(
            "INSERT INTO election_settings (division, deadline, is_active) VALUES (?, NULL, 1)",
            (teacher_division,)
        )
        conn.commit()
        voting_deadline = None
        is_active = True
    else:
        voting_deadline = setting["deadline"]
        is_active = setting["is_active"]

    # Get vote count for this division
    vote_count = conn.execute("""
        SELECT COUNT(*) FROM votes 
        WHERE candidate_id IN (
            SELECT id FROM candidates WHERE division = ?
        )
    """, (teacher_division,)).fetchone()[0]

    # Get number of students who have voted for both categories
    students_voted_both = conn.execute("""
        SELECT student_id, COUNT(DISTINCT category) as categories_voted
        FROM votes 
        WHERE candidate_id IN (
            SELECT id FROM candidates WHERE division = ?
        )
        GROUP BY student_id
        HAVING categories_voted = 2
    """, (teacher_division,)).fetchall()
    
    students_completed_voting = len(students_voted_both)

    conn.close()

    return render_template(
        "teacher_dashboard.html",
        teacher_division=teacher_division,
        boys_rep_count=boys_rep_count,
        girls_rep_count=girls_rep_count,
        voting_deadline=voting_deadline,
        is_active=is_active,
        vote_count=vote_count,
        students_completed_voting=students_completed_voting
    )


# ================= SET DIVISION-SPECIFIC DEADLINE =================
@app.route("/set_deadline", methods=["POST"])
def set_deadline():
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))

    deadline = request.form.get("deadline")
    division = session["teacher_division"]

    if not deadline:
        return redirect(url_for("teacher_dashboard"))

    conn = get_db()

    # Update or insert deadline for specific division
    conn.execute(
        """INSERT OR REPLACE INTO election_settings (division, deadline, is_active) 
        VALUES (?, ?, 1)""",
        (division, deadline)
    )
    conn.commit()
    conn.close()

    return redirect(url_for("teacher_dashboard"))


# ================= ADD CANDIDATE =================
@app.route("/teacher/<division>/add_candidate", methods=["GET", "POST"])
def add_candidate_division(division):
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))

    conn = get_db()

    # Get teacher division
    teacher = conn.execute(
        "SELECT division FROM teachers WHERE id=?",
        (session["teacher_id"],)
    ).fetchone()

    # Unauthorized access protection
    if teacher is None or teacher["division"] != division:
        conn.close()
        return "Unauthorized access", 403

    # POST: ADD CANDIDATE
    if request.method == "POST":
        name = request.form.get("name")
        category = request.form.get("category")
        gender = request.form.get("gender")

        if name and category and gender:
            # Prevent duplicate candidate
            exists = conn.execute(
                "SELECT 1 FROM candidates WHERE name=? AND category=? AND division=?",
                (name.strip(), category, division)
            ).fetchone()

            if not exists:
                conn.execute(
                    "INSERT INTO candidates (name, category, division, gender) VALUES (?, ?, ?, ?)",
                    (name.strip(), category, division, gender)
                )
                conn.commit()

        conn.close()
        return redirect(url_for("add_candidate_division", division=division))

    # GET: SHOW PAGE
    candidates = conn.execute(
        "SELECT * FROM candidates WHERE division=? ORDER BY category, name",
        (division,)
    ).fetchall()

    conn.close()

    return render_template(
        "add_candidate.html",
        candidates=candidates,
        division=division
    )


# ================= DELETE CANDIDATE =================
@app.route("/teacher/<division>/delete_candidate/<int:id>", methods=["POST"])
def delete_candidate_division(division, id):
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))

    conn = get_db()

    teacher = conn.execute(
        "SELECT division FROM teachers WHERE id=?",
        (session["teacher_id"],)
    ).fetchone()

    if teacher is None or teacher["division"] != division:
        conn.close()
        return "Unauthorized", 403

    conn.execute(
        "DELETE FROM candidates WHERE id=? AND division=?",
        (id, division)
    )
    conn.commit()
    conn.close()

    return redirect(url_for("add_candidate_division", division=division))


# ================= STUDENT SIGNUP =================
@app.route("/student_signup", methods=["GET", "POST"])
def student_signup():
    if request.method == "POST":
        name = request.form["name"]
        prn = request.form["prn"]
        division = request.form["div"]
        year = request.form["year"]
        email = request.form["email"]
        password = request.form["password"]
        gender = request.form.get("gender", "")

        conn = get_db()
        try:
            conn.execute("""
            INSERT INTO students (name, prn, division, year, email, password, gender)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, prn, division, year, email, password, gender))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "PRN already exists"

        conn.close()
        return redirect(url_for("student_login"))

    return render_template("student_signup.html")


# ================= STUDENT LOGIN =================
@app.route("/student_login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        prn = request.form["prn"]
        password = request.form["password"]

        conn = get_db()
        student = conn.execute(
            "SELECT * FROM students WHERE prn=? AND password=?",
            (prn, password)
        ).fetchone()
        conn.close()

        if student:
            session["student_id"] = student["id"]
            session["student_division"] = student["division"]
            # FIX: Use dict() to convert sqlite3.Row to dictionary
            student_dict = dict(student)
            session["student_gender"] = student_dict.get("gender", "")
            return redirect(url_for("student_dashboard"))

        return "Invalid PRN or Password"

    return render_template("student_login.html")


# ================= STUDENT DASHBOARD =================
@app.route("/student/dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect(url_for("student_login"))

    conn = get_db()
    
    # Get student's division and voting status
    student = conn.execute(
        "SELECT division, gender FROM students WHERE id=?",
        (session["student_id"],)
    ).fetchone()
    
    if not student:
        conn.close()
        session.clear()
        return redirect(url_for("student_login"))
    
    # Convert sqlite3.Row to dictionary
    student_dict = dict(student)
    
    # Check which categories the student has voted for
    student_votes = conn.execute(
        "SELECT category FROM votes WHERE student_id=?",
        (session["student_id"],)
    ).fetchall()
    
    voted_categories = [vote["category"] for vote in student_votes]
    
    conn.close()
    
    return render_template("student_dashboard.html", 
                         student_division=student_dict["division"],
                         student_gender=student_dict.get("gender", ""),
                         voted_categories=voted_categories)


# ================= VOTE BY CATEGORY =================
@app.route("/vote/<category>", methods=["GET", "POST"])
def vote_category(category):
    if "student_id" not in session:
        return redirect(url_for("student_login"))

    conn = get_db()
    student_id = session["student_id"]
    
    # Get student information
    student = conn.execute(
        "SELECT division, gender FROM students WHERE id=?",
        (student_id,)
    ).fetchone()
    
    if not student:
        conn.close()
        session.clear()
        return redirect(url_for("student_login"))
    
    # Convert to dictionary for safe access
    student_dict = dict(student)
    student_division = student_dict["division"]
    student_gender = student_dict.get("gender", "")
    
    # Update session
    session["student_division"] = student_division
    session["student_gender"] = student_gender

    # Division-specific deadline check
    deadline_row = conn.execute(
        "SELECT deadline FROM election_settings WHERE division=?",
        (student_division,)
    ).fetchone()

    if deadline_row and deadline_row["deadline"]:
        deadline = datetime.strptime(
            deadline_row["deadline"],
            "%Y-%m-%dT%H:%M"
        )
        if datetime.now() > deadline:
            conn.close()
            # Redirect to division-specific results
            return redirect(url_for("division_results", division=student_division))

    # Already voted for this category?
    already_voted = conn.execute(
        "SELECT * FROM votes WHERE student_id=? AND category=?",
        (student_id, category)
    ).fetchone()

    if already_voted:
        conn.close()
        category_name = "Boys Representative" if category == "boys_representative" else "Girls Representative"
        return f"✅ You have already voted for {category_name}. You can vote for the other representative category."

    # POST: submit vote
    if request.method == "POST":
        candidate_id = request.form.get("candidate_id")

        # Division security
        candidate = conn.execute(
            "SELECT division, category FROM candidates WHERE id=?",
            (candidate_id,)
        ).fetchone()

        if candidate["division"] != student_division:
            conn.close()
            return "❌ You are not allowed to vote for this division"

        # NO GENDER RESTRICTION - ALL STUDENTS CAN VOTE FOR BOTH CATEGORIES
        # Students can vote for both Boys Representative AND Girls Representative
        
        conn.execute(
            "INSERT INTO votes (student_id, category, candidate_id) VALUES (?, ?, ?)",
            (student_id, category, candidate_id)
        )
        conn.commit()
        conn.close()

        category_name = "Boys Representative" if category == "boys_representative" else "Girls Representative"
        return f"✅ Vote submitted for {category_name}! You can still vote for the other representative."

    # GET: show candidates by category + division
    candidates = conn.execute(
        "SELECT * FROM candidates WHERE category=? AND division=?",
        (category, student_division)
    ).fetchall()

    conn.close()
    
    category_name = "Boys Representative" if category == "boys_representative" else "Girls Representative"
    
    return render_template(
        "vote_category.html",
        candidates=candidates,
        category=category,
        category_name=category_name,
        division=student_division,
        student_gender=student_gender
    )


# ================= GLOBAL RESULTS (FOR COMPATIBILITY) =================
@app.route("/results")
def results():
    # Check if student is logged in
    if "student_id" in session:
        division = session.get("student_division")
        if division:
            return redirect(url_for("division_results", division=division))
    
    # If teacher is logged in
    if "teacher_id" in session:
        division = session.get("teacher_division")
        if division:
            return redirect(url_for("division_results", division=division))
    
    # Otherwise show all results
    return redirect(url_for("all_results"))


# ================= DIVISION-SPECIFIC RESULTS =================
@app.route("/results/<division>")
def division_results(division):
    conn = get_db()

    # Check if voting is still active for this division
    deadline_row = conn.execute(
        "SELECT deadline FROM election_settings WHERE division=?",
        (division,)
    ).fetchone()

    show_results = True
    
    if deadline_row and deadline_row["deadline"]:
        deadline = datetime.strptime(
            deadline_row["deadline"],
            "%Y-%m-%dT%H:%M"
        )
        if datetime.now() < deadline:
            show_results = False
            remaining_time = deadline - datetime.now()
    else:
        # No deadline set, show results anyway
        show_results = True

    if show_results:
        # Get results grouped by category
        results = conn.execute("""
            SELECT c.category, c.name, 
                   COALESCE(c.gender, 'Not specified') as gender, 
                   COUNT(v.id) AS total_votes
            FROM candidates c
            LEFT JOIN votes v ON c.id = v.candidate_id
            WHERE c.division = ?
            GROUP BY c.id, c.category
            ORDER BY c.category, total_votes DESC
        """, (division,)).fetchall()

        # Get winner for each category
        categories = {}
        for row in results:
            cat = row["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(dict(row))  # Convert to dictionary

        winners = {}
        for category, candidates_list in categories.items():
            if candidates_list:
                # Sort by votes descending
                candidates_list.sort(key=lambda x: x["total_votes"], reverse=True)
                winners[category] = candidates_list[0]

        # Get total votes per category
        total_votes_boys = conn.execute("""
            SELECT COUNT(*) FROM votes v 
            JOIN candidates c ON v.candidate_id = c.id 
            WHERE c.division = ? AND c.category = 'boys_representative'
        """, (division,)).fetchone()[0]
        
        total_votes_girls = conn.execute("""
            SELECT COUNT(*) FROM votes v 
            JOIN candidates c ON v.candidate_id = c.id 
            WHERE c.division = ? AND c.category = 'girls_representative'
        """, (division,)).fetchone()[0]

        conn.close()
        
        # Convert categories values to dictionaries for template
        categories_for_template = {}
        for cat, cand_list in categories.items():
            categories_for_template[cat] = []
            for cand in cand_list:
                categories_for_template[cat].append({
                    'name': cand['name'],
                    'gender': cand['gender'],
                    'total_votes': cand['total_votes']
                })
        
        # Convert winners to dictionaries
        winners_for_template = {}
        for cat, winner in winners.items():
            winners_for_template[cat] = {
                'name': winner['name'],
                'gender': winner['gender'],
                'total_votes': winner['total_votes']
            }
        
        return render_template(
            "results.html", 
            results=results, 
            division=division, 
            show_results=True,
            categories=categories_for_template,
            winners=winners_for_template,
            total_votes_boys=total_votes_boys,
            total_votes_girls=total_votes_girls
        )
    else:
        conn.close()
        hours = remaining_time.seconds // 3600
        minutes = (remaining_time.seconds % 3600) // 60
        return render_template(
            "results.html",
            division=division,
            show_results=False,
            remaining_days=remaining_time.days,
            remaining_hours=hours,
            remaining_minutes=minutes
        )


# ================= ALL RESULTS (ADMIN VIEW) =================
@app.route("/all_results")
def all_results():
    # For admin to see all divisions
    conn = get_db()

    # Get all divisions
    divisions = conn.execute(
        "SELECT DISTINCT division FROM election_settings"
    ).fetchall()

    division_data = []
    for div_row in divisions:
        division = div_row["division"]
        
        # Get results for this division
        results = conn.execute("""
            SELECT c.category, c.name, 
                   COALESCE(c.gender, 'Not specified') as gender, 
                   COUNT(v.id) AS total_votes
            FROM candidates c
            LEFT JOIN votes v ON c.id = v.candidate_id
            WHERE c.division = ?
            GROUP BY c.id, c.category
            ORDER BY c.category, total_votes DESC
        """, (division,)).fetchall()
        
        # Convert results to dictionaries
        results_list = []
        for row in results:
            results_list.append(dict(row))
        
        division_data.append({
            'division': division,
            'results': results_list
        })

    conn.close()
    return render_template("all_results.html", division_data=division_data)


# ================= RESET DIVISION-SPECIFIC ELECTION =================
@app.route("/reset_election", methods=["POST"])
def reset_election():
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))

    teacher_division = session["teacher_division"]
    
    conn = get_db()

    # Delete only votes for candidates of this division
    conn.execute("""
        DELETE FROM votes 
        WHERE candidate_id IN (
            SELECT id FROM candidates WHERE division = ?
        )
    """, (teacher_division,))

    # Delete only candidates of this division
    conn.execute("DELETE FROM candidates WHERE division = ?", (teacher_division,))

    # Reset deadline for this division only
    conn.execute("""
        UPDATE election_settings
        SET deadline = NULL, is_active = 1
        WHERE division = ?
    """, (teacher_division,))

    conn.commit()
    conn.close()

    return redirect(url_for("teacher_dashboard"))


# ================= TOGGLE ELECTION STATUS =================
@app.route("/toggle_election", methods=["POST"])
def toggle_election():
    if "teacher_id" not in session:
        return redirect(url_for("teacher_login"))

    teacher_division = session["teacher_division"]
    
    conn = get_db()
    
    # Get current status
    setting = conn.execute(
        "SELECT is_active FROM election_settings WHERE division=?",
        (teacher_division,)
    ).fetchone()
    
    if setting:
        new_status = 0 if setting["is_active"] else 1
        conn.execute(
            "UPDATE election_settings SET is_active=? WHERE division=?",
            (new_status, teacher_division)
        )
        conn.commit()
    
    conn.close()
    return redirect(url_for("teacher_dashboard"))


# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ================= RUN =================
if __name__ == "__main__":
    init_db()   # FORCE create tables first
    app.run(debug=True, port=5000)
