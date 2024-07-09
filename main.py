from flask import Flask, request, jsonify, session
import pymysql
import uuid
import hashlib
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)

# MySQL configurations
db = pymysql.connect(
    host='localhost',
    user='your_username',
    password='your_password',
    database='your_database',
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
    user_id = data.get('ID')
    password = data.get('PW')

    with db.cursor() as cur:
        cur.execute('SELECT * FROM Users WHERE user_id = %s', (user_id,))
        user = cur.fetchone()

    if user:
        hashed_password = hash_password(password, user['salt'])
        if hashed_password == user['Pw']:
            session_id = str(uuid.uuid4())
            with db.cursor() as cur:
                cur.execute('INSERT INTO Session (user_id, session_id) VALUES (%s, %s)', (user['user_id'], session_id))
                db.commit()

            session['session_id'] = session_id
            session['user_id'] = user['user_id']
            session['name'] = user['name']

            return jsonify({'message': '로그인 성공', 'session_id': session_id}), 200
        else:
            return jsonify({'message': '비밀번호가 일치하지 않습니다.'}), 401
    else:
        return jsonify({'message': '사용자를 찾을 수 없습니다.'}), 404

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    user_id = data.get('ID')
    name = data.get('이름')
    password = data.get('PW')
    selected_subject = data.get('선택한 과목')

    with db.cursor() as cur:
        cur.execute('SELECT * FROM Users WHERE user_id = %s', (user_id,))
        existing_user = cur.fetchone()

        if existing_user:
            return jsonify({'message': '이미 존재하는 학번입니다.'}), 409

        salt = generate_salt()
        hashed_password = hash_password(password, salt)

        cur.execute(
            'INSERT INTO Users (user_id, name, Pw, security_question, security_answer, salt) VALUES (%s, %s, %s, %s, %s, %s)',
            (user_id, name, hashed_password, data.get('security_question'), data.get('security_answer'), salt)
        )
        db.commit()

        if selected_subject:
            cur.execute('SELECT * FROM Subject WHERE subject_name = %s', (selected_subject,))
            subject = cur.fetchone()
            if not subject:
                cur.execute('INSERT INTO Subject (subject_name, teacher) VALUES (%s, %s)', (selected_subject, data.get('선생님')))
                db.commit()

        session_id = str(uuid.uuid4())
        cur.execute('INSERT INTO Session (user_id, session_id) VALUES (%s, %s)', (user_id, session_id))
        db.commit()

    session['session_id'] = session_id
    session['user_id'] = user_id
    session['name'] = name

    return jsonify({'message': '회원가입이 완료되었습니다.', 'session_id': session_id}), 201

@app.route('/search_pw', methods=['POST'])
def search_password():
    data = request.json
    user_id = data.get('user_id')
    security_question_answer = data.get('security_answer')

    with db.cursor() as cur:
        cur.execute('SELECT * FROM Users WHERE user_id = %s', (user_id,))
        user = cur.fetchone()

        if not user:
            return jsonify({'message': '존재하지 않는 사용자입니다.'}), 404

        if user['security_answer'] != security_question_answer:
            return jsonify({'message': '보안 질문의 답변이 일치하지 않습니다.'}), 401

        reset_token = str(uuid.uuid4())
        cur.execute('INSERT INTO Tokens (user_id, token) VALUES (%s, %s)', (user_id, reset_token))
        db.commit()

    return jsonify({'message': '비밀번호 초기화를 위한 권한이 부여되었습니다.', 'reset_token': reset_token}), 200

@app.route('/list', methods=['GET'])
def get_post_list():
    filter_type = request.args.get('filter')
    sort_by = request.args.get('sort_by')
    division = request.args.get('division')
    search_query = request.args.get('search_query')

    sql = "SELECT p.post_id, p.category, p.title, u.name AS author, p.date_time, COUNT(pl.id) AS likes_count " \
          "FROM Posts p " \
          "LEFT JOIN Users u ON p.user_id = u.user_id " \
          "LEFT JOIN PostLike pl ON p.post_id = pl.post_id " \
          "WHERE 1=1"

    if filter_type:
        sql += f" AND p.category = '{filter_type}'"
    if division == '과목':
        sql += " AND p.subject_id IS NOT NULL"
    if search_query:
        sql += f" AND (p.title LIKE '%{search_query}%' OR p.content LIKE '%{search_query}%')"

    if sort_by == '조회수 순':
        sql += " GROUP BY p.post_id ORDER BY COUNT(pl.id) DESC"
    elif sort_by == '좋아요 순':
        sql += " GROUP BY p.post_id ORDER BY likes_count DESC"
    elif sort_by == '날짜 순':
        sql += " ORDER BY p.date_time DESC"

    with db.cursor() as cur:
        cur.execute(sql)
        posts = cur.fetchall()

    return jsonify({'posts': posts}), 200

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
            'INSERT INTO Posts (user_id, title, content, category, date_time) VALUES (%s, %s, %s, %s, %s)',
            (user_id, title, content, category, date_time)
        )
        db.commit()

    return jsonify({'message': '글이 생성됨을 알림'}), 200

@app.route('/article', methods=['GET'])
def get_article():
    post_id = request.args.get('post_id')

    if not post_id:
        return jsonify({'error': 'Missing post_id parameter'}), 400

    user_id = get_user_id_from_session()
    with db.cursor() as cur:
        cur.execute(
            "SELECT p.category, p.title, p.content, u.name AS author, "
            "s.subject_name AS selected_subject, p.date_time, "
            "(SELECT COUNT(*) FROM post_like WHERE post_id = %s) AS like_count, "
            "(SELECT COUNT(*) FROM post_like WHERE post_id = %s AND user_id = %s) AS liked "
            "FROM Posts p "
            "LEFT JOIN Users u ON p.user_id = u.user_id "
            "LEFT JOIN User_Subject us ON p.user_id = us.user_id "
            "LEFT JOIN Subject s ON us.subject_id = s.subject_id "
            "WHERE p.post_id = %s",
            (post_id, post_id, user_id, post_id)
        )
        result = cur.fetchone()

    if not result:
        return jsonify({'error': 'Post not found'}), 404

    return jsonify(result), 200

if __name__ == '__main__':
    app.run(debug=True)
