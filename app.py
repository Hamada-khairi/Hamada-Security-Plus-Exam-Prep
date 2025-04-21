from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, send_file, abort, session
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
import io
import csv
from datetime import datetime
from sqlalchemy import func
import random
import json
from datetime import datetime
import os
from io import BytesIO
import base64
import shutil

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///securityplus.db'
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Add configuration for file uploads
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create uploads directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    is_marked = db.Column(db.Boolean, default=False)
    image_url = db.Column(db.String(200))

class ExamHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    time_taken = db.Column(db.Integer)  # in seconds
    date_taken = db.Column(db.DateTime, default=datetime.utcnow)
    incorrect_questions = db.Column(db.Text)  # Store comma-separated question IDs

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
    # Get user's exam history
    exam_history = ExamHistory.query.filter_by(user_id=current_user.id).order_by(ExamHistory.date_taken.desc()).all()
    
    # Calculate statistics
    total_exams = len(exam_history)
    total_questions = sum(exam.total_questions for exam in exam_history)
    average_score = sum(exam.score for exam in exam_history) / total_exams if total_exams > 0 else 0
    
    # Get all questions for the question bank
    questions = Question.query.order_by(Question.id.desc()).all()
    
    # Get question categories
    categories = db.session.query(Question.category).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]]  # Remove None values
    
    return render_template('dashboard.html',
                         exam_history=exam_history,
                         exams_taken=total_exams,
                         total_questions=total_questions,
                         average_score=round(average_score, 1),
                         questions=questions,
                         categories=categories)

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

@app.route('/toggle-mark-question/<int:question_id>', methods=['POST'])
@login_required
def toggle_mark_question(question_id):
    question = Question.query.get_or_404(question_id)
    if not hasattr(question, 'is_marked'):
        question.is_marked = False
    question.is_marked = not question.is_marked
    db.session.commit()
    return jsonify({'success': True, 'is_marked': question.is_marked})

@app.route('/delete-question/<int:question_id>')
@login_required
def delete_question_redirect(question_id):
    question = Question.query.get_or_404(question_id)
    db.session.delete(question)
    db.session.commit()
    flash('Question deleted successfully.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/delete-all-questions', methods=['POST'])
@login_required
def delete_all_questions():
    Question.query.delete()
    db.session.commit()
    flash('All questions have been deleted')
    return redirect(url_for('dashboard'))

@app.route('/edit-question/<int:question_id>', methods=['GET'])
@login_required
def edit_question(question_id):
    question = Question.query.get_or_404(question_id)
    categories = db.session.query(Question.category).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]] or []  # Handle empty categories
    return render_template('edit_question.html', 
                         question=question,
                         categories=categories)

@app.route('/update-question/<int:question_id>', methods=['POST'])
@login_required
def update_question(question_id):
    question = Question.query.get_or_404(question_id)
    
    # Handle image upload
    if 'image' in request.files:
        file = request.files['image']
        if file and allowed_file(file.filename):
            # Remove old image if exists
            if question.image_url:
                old_image_path = os.path.join(app.root_path, question.image_url.lstrip('/'))
                if os.path.exists(old_image_path):
                    os.remove(old_image_path)
            
            # Save new image
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename))
            question.image_url = f'/static/uploads/{filename}'
    
    # Handle image removal
    if request.form.get('remove_image') and question.image_url:
        old_image_path = os.path.join(app.root_path, question.image_url.lstrip('/'))
        if os.path.exists(old_image_path):
            os.remove(old_image_path)
        question.image_url = None
    
    # Update other fields
    question.question_text = request.form['question_text']
    question.options = request.form.getlist('options[]')
    question.correct_answers = [int(x) for x in request.form.getlist('correct_answers[]')]
    question.explanation = request.form.get('explanation', '')
    question.category = request.form.get('category', '')
    
    db.session.commit()
    
    # Check if we need to return to exam
    return_to_exam = request.form.get('return_to_exam')
    exam_index = request.form.get('exam_index')
    
    if return_to_exam and exam_index:
        flash('Question updated successfully!', 'success')
        return redirect(url_for('resume_exam', index=exam_index))
    
    flash('Question updated successfully!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/add-question', methods=['GET', 'POST'])
@login_required
def add_question():
    if request.method == 'POST':
        # Handle image upload
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename))
                image_url = f'/static/uploads/{filename}'

        question = Question(
            question_text=request.form['question_text'],
            options=request.form.getlist('options[]'),
            correct_answers=[int(x) for x in request.form.getlist('correct_answers[]')],
            explanation=request.form.get('explanation', ''),
            category=request.form.get('category', ''),
            image_url=image_url
        )
        db.session.add(question)
        db.session.commit()
        
        flash('Question added successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    categories = db.session.query(Question.category).distinct().all()
    categories = [cat[0] for cat in categories if cat[0]] or []  # Handle empty categories
    return render_template('add_question.html', 
                         question=None,
                         categories=categories)

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
    mode = request.form.get('mode', 'timed')
    is_timed = mode == 'timed'
    
    # Get exam settings
    settings = {
        'shuffle_questions': request.form.get('shuffle_questions') == 'on',
        'shuffle_answers': request.form.get('shuffle_answers') == 'on',
        'show_explanations': request.form.get('show_explanations') == 'on',
        'passing_score': int(request.form.get('passing_score', 70))
    }
    
    # Get questions based on mode and filters
    if mode == 'review_mistakes':
        # Get incorrect questions from previous exams
        incorrect_questions = set()
        recent_exams = ExamHistory.query.filter_by(user_id=current_user.id).order_by(ExamHistory.date_taken.desc()).limit(5).all()
        
        print("Found", len(recent_exams), "recent exams")  # Debug log
        
        for exam in recent_exams:
            print(f"Exam {exam.id} incorrect questions: {exam.incorrect_questions}")  # Debug log
            if exam.incorrect_questions:
                incorrect_question_ids = [int(id) for id in exam.incorrect_questions.split(',') if id]
                incorrect_questions.update(incorrect_question_ids)
        
        print("Total incorrect questions found:", len(incorrect_questions))  # Debug log
        
        if not incorrect_questions:
            flash('No incorrect questions found from recent exams. Try taking a regular exam first.', 'info')
            return redirect(url_for('dashboard'))
            
        questions = Question.query.filter(Question.id.in_(incorrect_questions))
        if settings['shuffle_questions']:
            questions = questions.order_by(func.random())
        questions = questions.limit(num_questions).all()
    else:
        # Regular question selection
        questions = Question.query.order_by(func.random() if settings['shuffle_questions'] else Question.id)
        
        # Apply category filters if provided
        categories = request.form.getlist('categories[]')
        if categories:
            questions = questions.filter(Question.category.in_(categories))
        
        questions = questions.limit(num_questions).all()
    
    if not questions:
        flash('No questions available. Please add questions first.', 'error')
        return redirect(url_for('dashboard'))
    
    questions_data = [
        {
            'id': q.id,
            'question_text': q.question_text,
            'options': q.options if not settings['shuffle_answers'] else random.sample(q.options, len(q.options)),
            'correct_answers': q.correct_answers,
            'explanation': q.explanation,
            'image_url': q.image_url
        } for q in questions
    ]
    
    return render_template('exam.html', 
                          questions=questions_data,
                          mode=mode,
                          settings=settings,
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

@app.route('/finish-exam', methods=['POST'])
@login_required
def finish_exam():
    data = request.get_json()
    incorrect_questions = data.get('incorrect_questions', [])
    
    print("Received incorrect questions:", incorrect_questions)  # Debug log
    
    exam_history = ExamHistory(
        user_id=current_user.id,
        score=round(data['score'], 1),
        total_questions=data['total_questions'],
        time_taken=data['time_taken'],
        incorrect_questions=','.join(map(str, incorrect_questions)) if incorrect_questions else None
    )
    
    print("Saving incorrect questions:", exam_history.incorrect_questions)  # Debug log
    
    db.session.add(exam_history)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'redirect_url': url_for('exam_results', exam_id=exam_history.id)
    })

@app.route('/exam-results/<int:exam_id>')
@login_required
def exam_results(exam_id):
    exam = ExamHistory.query.get_or_404(exam_id)
    if exam.user_id != current_user.id:
        abort(403)
    
    return render_template('exam_results.html', exam=exam)

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

@app.route('/resume-exam')
@login_required
def resume_exam():
    index = request.args.get('index', 0, type=int)
    # Add the index to the session so the exam page knows where to resume
    session['resume_index'] = index
    return redirect(url_for('start_exam'))

@app.route('/question-bank')
@login_required
def question_bank():
    questions = Question.query.all()
    categories = db.session.query(Question.category).distinct()
    categories = [cat[0] for cat in categories if cat[0]]  # Remove None values
    return render_template('question_bank.html', questions=questions, categories=categories)

@app.route('/export-question-bank')
@login_required
def export_question_bank():
    questions = Question.query.all()
    
    # Prepare the export data
    export_data = {
        'version': '1.0',
        'timestamp': datetime.now().isoformat(),
        'total_questions': len(questions),
        'questions': []
    }
    
    for q in questions:
        question_data = {
            'question_text': q.question_text,
            'options': q.options,
            'correct_answers': q.correct_answers,
            'explanation': q.explanation,
            'category': q.category,
            'is_marked': q.is_marked
        }
        
        # If question has an image, include it as base64
        if q.image_url:
            try:
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], q.image_url)
                if os.path.exists(image_path):
                    with open(image_path, 'rb') as img_file:
                        img_data = base64.b64encode(img_file.read()).decode('utf-8')
                        # Get file extension
                        _, ext = os.path.splitext(q.image_url)
                        question_data['image'] = {
                            'data': img_data,
                            'extension': ext.lstrip('.'),
                            'original_name': q.image_url
                        }
            except Exception as e:
                print(f"Error processing image for question {q.id}: {e}")
        
        export_data['questions'].append(question_data)
    
    # Create the export file content with proper formatting
    export_content = json.dumps(export_data, indent=2, ensure_ascii=False)
    
    # Create response with file download
    buffer = BytesIO()
    buffer.write(export_content.encode('utf-8'))
    buffer.seek(0)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        buffer,
        mimetype='application/json',
        as_attachment=True,
        download_name=f'security_plus_question_bank_{timestamp}.json'
    )

@app.route('/import-question-bank', methods=['POST'])
@login_required
def import_question_bank():
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('question_bank'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('question_bank'))
    
    if not file.filename.endswith('.json'):
        flash('Please upload a JSON file', 'error')
        return redirect(url_for('question_bank'))
    
    try:
        content = file.read().decode('utf-8')
        import_data = json.loads(content)
        
        # Validate import data structure
        if not isinstance(import_data, dict) or 'questions' not in import_data:
            flash('Invalid question bank file format', 'error')
            return redirect(url_for('question_bank'))
        
        questions_imported = 0
        images_imported = 0
        
        for data in import_data['questions']:
            # Create new question
            question = Question(
                question_text=data['question_text'],
                options=data['options'],
                correct_answers=data['correct_answers'],
                explanation=data.get('explanation'),
                category=data.get('category'),
                is_marked=data.get('is_marked', False)
            )
            
            # Handle image if present
            if 'image' in data and isinstance(data['image'], dict):
                try:
                    img_data = base64.b64decode(data['image']['data'])
                    ext = data['image'].get('extension', 'png')
                    
                    # Generate unique filename
                    filename = f"question_img_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{questions_imported}.{ext}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    # Save image
                    with open(filepath, 'wb') as f:
                        f.write(img_data)
                    
                    question.image_url = filename
                    images_imported += 1
                except Exception as e:
                    print(f"Error saving image: {e}")
            
            db.session.add(question)
            questions_imported += 1
        
        db.session.commit()
        flash(f'Successfully imported {questions_imported} questions and {images_imported} images', 'success')
    except json.JSONDecodeError:
        flash('Invalid JSON file format', 'error')
    except Exception as e:
        flash(f'Error importing questions: {str(e)}', 'error')
    
    return redirect(url_for('question_bank'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
