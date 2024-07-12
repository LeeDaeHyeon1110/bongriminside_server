from flask import Flask, request, jsonify, session, Response
from flask_session import Session
import pymysql
import os
from dotenv import load_dotenv
from datetime import datetime
import uuid
import hashlib
import redis

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

# Redis configuration
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = redis.Redis(host='localhost', port=6379)

# Initialize the session
Session(app)

# MySQL configurations
db = pymysql.connect(
    host=os.getenv('DB_HOST'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    database=os.getenv('DB_NAME'),
    cursorclass=pymysql.cursors.DictCursor
)

def generate_salt():
    return uuid.uuid4().hex

def hash_password(password, salt):
    return hashlib.sha256((password + salt).encode()).hexdigest()

def get_user_id_from_session():
    return session.get('user_id')

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    student_id = data.get('ID')
    password = data.get('PW')

    with db.cursor() as cur:
        cur.execute('SELECT * FROM Users WHERE student_id = %s', (student_id,))
        user = cur.fetchone()

    if user:
        hashed_password = hash_password(password, user['salt'])
        if hashed_password == user['pw']:
            session['user_id'] = user['user_id']
            session['name'] = user['name']
            return jsonify({'message': '로그인 성공'}), 200
        else:
            return jsonify({'message': '비밀번호가 일치하지 않습니다.'}), 401
    else:
        return jsonify({'message': '사용자를 찾을 수 없습니다.'}), 404

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    student_id = data.get('ID')
    name = data.get('이름')
    password = data.get('PW')
    selected_subject = data.get('선택한 과목')
    teacher = data.get('선생님')
    security_question = data.get('security_question')
    security_answer = data.get('security_answer')

    with db.cursor() as cur:
        cur.execute('SELECT * FROM Users WHERE student_id = %s', (student_id,))
        existing_user = cur.fetchone()

        if existing_user:
            return jsonify({'message': '이미 존재하는 학번입니다.'}), 409

        salt = generate_salt()
        hashed_password = hash_password(password, salt)

        cur.execute(
            'INSERT INTO Users (student_id, name, pw, salt, security_question, security_answer) VALUES (%s, %s, %s, %s, %s, %s)',
            (student_id, name, hashed_password, salt, security_question, security_answer)
        )
        db.commit()

        # Retrieve the user_id of the newly created user
        cur.execute('SELECT user_id FROM Users WHERE student_id = %s', (student_id,))
        user = cur.fetchone()
        user_id = user['user_id']

        if selected_subject:
            cur.execute('SELECT * FROM Subjects WHERE subject_name = %s', (selected_subject,))
            subject = cur.fetchone()
            if not subject:
                cur.execute('INSERT INTO Subjects (subject_name, teacher) VALUES (%s, %s)', (selected_subject, teacher))
                db.commit()
                cur.execute('SELECT subject_id FROM Subjects WHERE subject_name = %s', (selected_subject,))
                subject = cur.fetchone()
            cur.execute('INSERT INTO SelectedSubjects (user_id, subject_id) VALUES (%s, %s)', (user_id, subject['subject_id']))
            db.commit()

        session['user_id'] = user_id
        session['name'] = name

    return jsonify({'message': '회원가입이 완료되었습니다.'}), 201

@app.route('/search_pw', methods=['POST'])
def search_password():
    data = request.json
    student_id = data.get('student_id')
    security_question_answer = data.get('security_answer')
    new_password = data.get('new_password')

    with db.cursor() as cur:
        cur.execute('SELECT * FROM Users WHERE student_id = %s', (student_id,))
        user = cur.fetchone()

        if not user:
            return jsonify({'message': '존재하지 않는 사용자입니다.'}), 404

        if user['security_answer'] != security_question_answer:
            return jsonify({'message': '보안 질문의 답변이 일치하지 않습니다.'}), 401

        salt = generate_salt()
        hashed_password = hash_password(new_password, salt)
        cur.execute('UPDATE Users SET pw = %s, salt = %s WHERE student_id = %s', (hashed_password, salt, student_id))
        db.commit()

    return jsonify({'message': '비밀번호가 성공적으로 변경되었습니다.'}), 200

@app.route('/article/write', methods=['POST'])
def write_article():
    file_binary = request.files.get('file_binary')
    title = request.form.get('title')
    content = request.form.get('content')
    category = request.form.get('category')

    if file_binary:
        file_path = os.path.join('/path/to/save/file', file_binary.filename)
        file_binary.save(file_path)

    user_id = get_user_id_from_session()

    if not user_id:
        return jsonify({'message': 'User not authenticated'}), 401

    with db.cursor() as cur:
        date_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur.execute(
            'INSERT INTO Posts (user_id, title, content, category, datetime) VALUES (%s, %s, %s, %s, %s)',
            (user_id, title, content, category, date_time)
        )
        db.commit()

    return jsonify({'message': '글이 생성됨을 알림'}), 200

@app.route('/article', methods=['GET'])
def get_article():
    post_id = request.args.get('post_id')

    if not post_id:
        return jsonify({'error': 'Missing post_id parameter'}), 400

    sql = """
        SELECT p.category, p.title, p.content, u.name AS author,
            s.subject_name AS selected_subject, p.datetime,
            p.view_count,
            COUNT(pl.id) AS like_count
        FROM Posts p
        LEFT JOIN Users u ON p.user_id = u.user_id
        LEFT JOIN Subjects s ON p.subject_id = s.subject_id
        LEFT JOIN PostLike pl ON p.post_id = pl.post_id
        WHERE p.post_id = %s
        GROUP BY p.post_id
    """

    with db.cursor() as cursor:
        cursor.execute(sql, (post_id,))
        article = cursor.fetchone()

    if not article:
        return jsonify({'error': 'Post not found'}), 404

    return jsonify(article), 200

@app.route('/article/delete', methods=['DELETE'])
def delete_article():
    post_id = request.args.get('post_id')

    if not post_id:
        return jsonify({'error': 'Missing post_id parameter'}), 400

    sql = "DELETE FROM Posts WHERE post_id = %s"
    with db.cursor() as cursor:
        cursor.execute(sql, (post_id,))
        db.commit()

    return Response(status=202)

@app.route('/comment', methods=["POST"])
def create_comment():
    post_id = request.json.get('post_id')
    content = request.json.get('content')
    user_id = get_user_id_from_session()
    datetime_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not user_id:
        return jsonify({'message': 'User not authenticated'}), 401

    sql = "INSERT INTO Comments (post_id, user_id, content, datetime) VALUES (%s, %s, %s, %s)"
    with db.cursor() as cursor:
        cursor.execute(sql, (post_id, user_id, content, datetime_now))
        db.commit()

    return Response(status=200)

@app.route('/comments', methods=["GET"])
def get_comments():
    post_id = request.args.get('post_id')
    user_id = get_user_id_from_session()

    if not user_id:
        return jsonify({'message': 'User not authenticated'}), 401

    sql = """
        SELECT u.name, c.content, c.datetime 
        FROM Comments c
        LEFT JOIN Users u ON u.user_id = c.user_id
        WHERE c.post_id = %s
    """

    with db.cursor() as cursor:
        cursor.execute(sql, (post_id,))
        comments = cursor.fetchall()

    return jsonify({'comments': comments}), 200

@app.route('/profile', methods=["GET"])
def get_profile():
    user_id = get_user_id_from_session()
    if not user_id:
        return jsonify({'message': 'User not authenticated'}), 401

    target_user_id = request.args.get("user_id")
    sql = "SELECT user_id, name FROM Users WHERE user_id = %s"

    with db.cursor() as cursor:
        cursor.execute(sql, (target_user_id,))
        user = cursor.fetchone()

    if not user:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({'user': user}), 200

@app.route('/list', methods=['GET'])
def get_post_list():
    # Parse query parameters
    filter_type = request.args.get('filter', default=None, type=str)
    sort_by = request.args.get('sort', default='datetime', type=str)  # Default sort by datetime
    subject_filter = request.args.get('subject', default='전체', type=str)  # Default filter to 전체
    search_query = request.args.get('q', default=None, type=str)

    # Base SQL query
    sql = """
        SELECT p.category, p.title, u.name AS author, p.datetime,
            p.view_count, COUNT(pl.id) AS like_count
        FROM Posts p
        LEFT JOIN Users u ON p.user_id = u.user_id
        LEFT JOIN PostLike pl ON p.post_id = pl.post_id
    """

    # Conditions to add to the query based on parameters
    conditions = []
    params = []

    if filter_type in ['공지', '질문', '자유']:
        conditions.append('p.category = %s')
        params.append(filter_type)

    if subject_filter != '전체':
        conditions.append('s.subject_name = %s')
        params.append(subject_filter)

    if search_query:
        conditions.append('(p.title LIKE %s OR p.content LIKE %s)')
        params.extend(['%' + search_query + '%', '%' + search_query + '%'])

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    # Group by post_id to avoid duplicates
    sql += " GROUP BY p.post_id"

    # Order by clause
    if sort_by == '조회수 순':
        sql += " ORDER BY p.view_count DESC"
    elif sort_by == '좋아요 순':
        sql += " ORDER BY like_count DESC"
    elif sort_by == '날짜 순':
        sql += " ORDER BY p.datetime DESC"

    with db.cursor() as cursor:
        cursor.execute(sql, params)
        posts = cursor.fetchall()

    return jsonify({'posts': posts}), 200

@app.route('/logout', methods=["DELETE"])
def logout():
    session.clear()
    return jsonify({'message': '로그아웃 완료'}), 200

if __name__ == '__main__':
    app.run(debug=True)
