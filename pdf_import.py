import PyPDF2
import re
from app import app, db, Question

def extract_questions_from_pdf(pdf_path):
    questions = []
    
    # Read and consolidate PDF text while cleaning page markers and headers.
    with open(pdf_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        full_text = ''
        for page in reader.pages:
            page_text = page.extract_text()
            # Remove extraneous page markers or headers like DumpsArena notices.
            page_text = re.sub(r'DumpsArena.*?Page \d+ of \d+', '', page_text, flags=re.DOTALL)
            full_text += page_text + '\n'
    
    # Normalize newlines for consistency.
    full_text = full_text.replace('\r\n', '\n')
    
    # Split the text into question blocks based on the "QUESTION NO:" markers.
    question_blocks = [block.strip() for block in re.split(r'QUESTION NO:\s*\d+', full_text) if block.strip()]
    
    for block in question_blocks:
        # Skip blocks that are too short
        if len(block) < 20:
            continue

        # --- Extract Question Text ---
        # Capture text from the beginning until the first option marker (e.g., "A.")
        question_text_match = re.search(r'^(.*?)(?=\n?[A-F]\.)', block, re.DOTALL)
        if question_text_match:
            question_text = question_text_match.group(1).strip()
        else:
            continue  # Skip block if question text not found

        # --- Extract Options ---
        options = []
        # Pattern for options: look for an uppercase letter (A-F) followed by a period.
        option_pattern = re.compile(r'([A-F])\.\s*(.*?)(?=\n(?:[A-F]\.)|ANSWER:|Explanation:|$)', re.DOTALL)
        for match in option_pattern.finditer(block):
            option_text = match.group(2).strip()
            # Clean any lingering noise (e.g., page markers)
            option_text = re.sub(r'DumpsArena.*?Page \d+ of \d+', '', option_text, flags=re.DOTALL)
            options.append(option_text)
        
        # --- Extract Correct Answers ---
        # This new pattern captures answer letters until it reaches "Explanation:" or "QUESTION NO:" or the end.
        answer_match = re.search(
            r'ANSWER:\s*([A-F](?:[,\s]+[A-F])*)(?=\s*(?:Explanation:|QUESTION NO:|$))',
            block,
            re.IGNORECASE
        )
        if answer_match:
            answer_text = answer_match.group(1).strip().upper()
            # Extract only the answer letters from the captured group.
            correct_answers = [ord(letter) - ord('A') for letter in re.findall(r'[A-F]', answer_text)]
        else:
            continue  # Skip block if no answer found
        
        # --- Extract Explanation ---
        explanation = ''
        explanation_match = re.search(r'Explanation:\s*(.*?)(?=\n?QUESTION NO:|$)', block, re.DOTALL)
        if explanation_match:
            explanation = explanation_match.group(1).strip()
            explanation = re.sub(r'DumpsArena.*?Page \d+ of \d+', '', explanation, flags=re.DOTALL)
        
        # --- Validate the Extracted Data ---
        if not question_text or len(options) < 2 or not correct_answers:
            continue
        
        # Build the question dictionary
        question = {
            'question_text': question_text,
            'options': options,
            'correct_answers': correct_answers,
            'explanation': explanation
        }
        questions.append(question)
    
    return questions

def import_questions_to_db(questions):
    with app.app_context():
        for q in questions:
            question = Question(
                question_text=q['question_text'],
                options=q['options'],
                correct_answers=q['correct_answers'],
                explanation=q['explanation']
            )
            db.session.add(question)
        db.session.commit()

if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print("Usage: python pdf_import.py <path_to_pdf>")
        sys.exit(1)
        
    pdf_path = sys.argv[1]
    questions = extract_questions_from_pdf(pdf_path)
    print(f"Extracted {len(questions)} questions from PDF.")
    import_questions_to_db(questions)
    print(f"Successfully imported {len(questions)} questions to the database.")
