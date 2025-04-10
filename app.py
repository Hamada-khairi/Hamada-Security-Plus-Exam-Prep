from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, send_file, abort
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
import io
import csv
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///securityplus.db'
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Database Models
class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    theme = db.Column(db.String(50), default='default')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    exam_history = db.relationship('ExamHistory', backref='user', lazy=True)
    settings = db.relationship('UserSettings', backref='user', uselist=False, lazy=True)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.Text, nullable=False)
    options = db.Column(db.JSON, nullable=False)
    correct_answers = db.Column(db.JSON, nullable=False)
    explanation = db.Column(db.Text)
    category = db.Column(db.String(100))

class ExamHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    time_taken = db.Column(db.Integer)  # in seconds
    date_taken = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
            
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        
        # Create default user settings
        settings = UserSettings(user_id=user.id)
        db.session.add(settings)
        db.session.commit()
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
            
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    questions = Question.query.all()
    user_exams = ExamHistory.query.filter_by(user_id=current_user.id).all()
    
    # Calculate statistics
    exams_taken = len(user_exams)
    total_questions = sum(exam.total_questions for exam in user_exams)
    average_score = sum(exam.score for exam in user_exams) / exams_taken if exams_taken > 0 else 0
    
    return render_template('dashboard.html', 
                           questions=questions,
                           exams_taken=exams_taken,
                           total_questions=total_questions,
                           average_score=round(average_score, 1))

@app.route('/upload-questions', methods=['POST'])
@login_required
def upload_questions():
    if 'pdf_file' not in request.files:
        flash('No file uploaded')
        return redirect(url_for('dashboard'))
        
    file = request.files['pdf_file']
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('dashboard'))
        
    if file and file.filename.endswith('.pdf'):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.instance_path, filename)
        os.makedirs(app.instance_path, exist_ok=True)
        file.save(file_path)
        
        try:
            from pdf_import import extract_questions_from_pdf, import_questions_to_db
            questions = extract_questions_from_pdf(file_path)
            import_questions_to_db(questions)
            flash(f'Successfully imported {len(questions)} questions')
            os.remove(file_path)  # Clean up the uploaded file
        except Exception as e:
            flash(f'Error processing PDF: {str(e)}')
            if os.path.exists(file_path):
                os.remove(file_path)
                
        return redirect(url_for('dashboard'))
    
    flash('Invalid file type. Please upload a PDF file.')
    return redirect(url_for('dashboard'))

@app.route('/delete-question/<int:question_id>', methods=['POST'])
@login_required
def delete_question(question_id):
    question = Question.query.get_or_404(question_id)
    db.session.delete(question)
    db.session.commit()
    flash('Question deleted successfully')
    return redirect(url_for('dashboard'))

@app.route('/delete-all-questions', methods=['POST'])
@login_required
def delete_all_questions():
    Question.query.delete()
    db.session.commit()
    flash('All questions have been deleted')
    return redirect(url_for('dashboard'))

@app.route('/edit-question/<int:question_id>')
@login_required
def edit_question(question_id):
    question = Question.query.get_or_404(question_id)
    return render_template('edit_question.html', question=question)

@app.route('/update-question/<int:question_id>', methods=['POST'])
@login_required
def update_question(question_id):
    question = Question.query.get_or_404(question_id)
    question.question_text = request.form['question_text']
    question.options = request.form.getlist('options[]')
    question.correct_answers = [int(x) for x in request.form.getlist('correct_answers[]')]
    question.explanation = request.form['explanation']
    
    db.session.commit()
    flash('Question updated successfully')
    return redirect(url_for('dashboard'))

@app.route('/add-question', methods=['GET', 'POST'])
@login_required
def add_question():
    if request.method == 'POST':
        question = Question(
            question_text=request.form['question_text'],
            options=request.form.getlist('options[]'),
            correct_answers=[int(x) for x in request.form.getlist('correct_answers[]')],
            explanation=request.form['explanation'],
            category=request.form.get('category')
        )
        db.session.add(question)
        db.session.commit()
        flash('Question added successfully')
        return redirect(url_for('dashboard'))
    return render_template('add_question.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/start-exam', methods=['POST'])
@login_required
def start_exam():
    num_questions = int(request.form.get('num_questions', 90))
    time_per_question = int(request.form.get('time_per_question', 1))
    is_timed = request.form.get('is_timed')
    
    questions = Question.query.order_by(db.func.random()).limit(num_questions).all()
    
    # Convert questions to a format suitable for JavaScript
    questions_data = [
        {
            'id': q.id,
            'question_text': q.question_text,
            'options': q.options,
            'correct_answers': q.correct_answers,
            'explanation': q.explanation
        } for q in questions
    ]
    
    return render_template('exam.html', 
                         questions=questions_data,
                         total_time=num_questions * time_per_question if is_timed else None)

@app.route('/submit-answer', methods=['POST'])
@login_required
def submit_answer():
    data = request.get_json()
    question_id = data.get('question_id')
    selected_answer = data.get('answer')
    
    question = Question.query.get_or_404(question_id)
    is_correct = set(selected_answer) == set(question.correct_answers)
    
    return jsonify({
        'correct': is_correct,
        'explanation': question.explanation,
        'correct_answers': question.correct_answers
    })

@app.route('/exam-analytics')
@login_required
def exam_analytics():
    # Get user's exam history
    user_exams = ExamHistory.query.filter_by(user_id=current_user.id).order_by(ExamHistory.date_taken.desc()).all()
    
    # Calculate overall statistics
    total_exams = len(user_exams)
    if total_exams > 0:
        avg_score = sum(exam.score for exam in user_exams) / total_exams
        best_score = max(exam.score for exam in user_exams)
        avg_time = sum(exam.time_taken for exam in user_exams if exam.time_taken) / total_exams
    else:
        avg_score = best_score = avg_time = 0
    
    # Get recent exams (last 5)
    recent_exams = user_exams[:5]
    
    return render_template('exam_analytics.html',
                           total_exams=total_exams,
                           avg_score=round(avg_score, 1),
                           best_score=round(best_score, 1),
                           avg_time=int(avg_time),
                           recent_exams=recent_exams)

@app.route('/view-exam-results/<int:exam_id>')
@login_required
def view_exam_results(exam_id):
    exam = ExamHistory.query.get_or_404(exam_id)
    # Ensure the exam belongs to the current user
    if exam.user_id != current_user.id:
        abort(403)
    return render_template('exam_results.html', exam=exam)

@app.route('/download-exam-results/<int:exam_id>')
@login_required
def download_exam_results(exam_id):
    exam = ExamHistory.query.get_or_404(exam_id)
    # Ensure the exam belongs to the current user
    if exam.user_id != current_user.id:
        abort(403)
        
    # Create CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Question', 'Your Answer', 'Correct Answer', 'Result', 'Explanation'])
    
    # Add exam data (this would need to be modified based on how you store exam answers)
    # This is a placeholder assuming you have the data in the exam history
    for question in exam.questions:
        writer.writerow([question.text, question.user_answer, 
                        question.correct_answer, question.is_correct, 
                        question.explanation])
    
    # Prepare the response
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'exam_results_{exam.date_taken.strftime("%Y%m%d_%H%M")}.csv'
    )

@app.route('/change-theme/<theme>')
@login_required
def change_theme(theme):
    valid_themes = ['default', 'onedark', 'blackgold', 'oceanic', 'purple']
    if theme not in valid_themes:
        flash('Invalid theme selection')
        return redirect(url_for('dashboard'))
    
    if not current_user.settings:
        settings = UserSettings(user_id=current_user.id, theme=theme)
        db.session.add(settings)
    else:
        current_user.settings.theme = theme
        current_user.settings.updated_at = datetime.utcnow()
    
    db.session.commit()
    return redirect(request.referrer or url_for('dashboard'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
