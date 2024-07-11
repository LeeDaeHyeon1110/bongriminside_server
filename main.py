from flask import Flask, request, jsonify, session, Response
import pymysql
import uuid
import hashlib
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)

# TODO: 이 부분을 dotenv와 같은것을 이용해서 코드에 노출되지 않도록 해야함
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

# TODO: 우리가 논의한 세션이 필요한 상황에서 세션이 이용되지 않은 부분이 많음

# TODO: 로그인 할 때에는 Sessions 테이블에 세션을 저장하는데,
# TODO: 막상 불러 오는 것은 flask의 Session 시스템 이용 중;

# ! 애플리케이션 환경에서는 쿠키를 넣어서 세션을 관리하는게 좋은가?

# * @app 위에 있는 주석이 해당 Endpoint에 접속할 때 필요한 매개변수 양식임
def get_user_id_from_session():
  return session.get('user_id')

# {
#   ID: string
#   PW: string
# }
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

# {
#   ID: string (len <= 4), 
#   이름: string, 
#   PW: string, 
#   security_question: string,
#   security_answer: string
#   선택한 과목: string, 
# ! 선생님: string
# }
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
      # TODO: 학생이 선택한 과목이 없으면 개설하는 구조로 되있음
      # TODO: 만약 이 방식을 이용하려면 프론트엔드한테 물어봐야함
      # TODO: 그리고 Subject 테이블에 추가할 과목을 넣은 다음 
      # TODO: 추가로 SelectedSubjects에 학생이 선택했다고도 추가를 해야함
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

# { 
#   user_id: string, 
#   security_answer: string
# }
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
    # TODO: Tokens라는 테이블로 초기화 권환 판단 
    # TODO:   => reset_token을 발행해서 비번 초기화 권한 부여
    
    # ! 본인인증과 동시에 비밀번호 바꿔줌으로 확정
    cur.execute('INSERT INTO Tokens (user_id, token) VALUES (%s, %s)', (user_id, reset_token))
    db.commit()

  return jsonify({'message': '비밀번호 초기화를 위한 권한이 부여되었습니다.', 'reset_token': reset_token}), 200

# { 
#   filter: string,  
#   sort_by: string (조회수 순, 좋아요 순, 날짜 순), 
#   division: (전체, 과목), 
#   search_query: string
# }
def get_post_list():
  filter_type = request.args.get('filter')  # 공지, 질문, 자유
  sort_by = request.args.get('sort_by')    # 조회수 순, 좋아요 순, 날짜 순
  division = request.args.get('division')  # 전체/과목
  search_query = request.args.get('search_query')  # 검색어

  # Base SQL query
  # TODO: 컬럼이름이 date_time 인가?
  sql = """
    SELECT p.post_id, p.category, p.title, u.name AS author, p.date_time,
            COUNT(pl.id) AS likes_count, COUNT(v.view_id) AS view_count
    FROM Posts p
    LEFT JOIN Users u ON p.user_id = u.user_id
    LEFT JOIN PostLike pl ON p.post_id = pl.post_id
    LEFT JOIN PostViews v ON p.post_id = v.post_id
    WHERE 1=1
  """

  # Applying filters based on query parameters
  if filter_type:
    sql += f" AND p.category = '{filter_type}'"

  if division == '과목':
    sql += " AND p.subject_id IS NOT NULL"

  if search_query:
    sql += f" AND (p.title LIKE '%{search_query}%' OR p.content LIKE '%{search_query}%')"

  # Sorting logic based on sort_by parameter
  if sort_by == '조회수 순':
    sql += " GROUP BY p.post_id ORDER BY view_count DESC"
  elif sort_by == '좋아요 순':
    sql += " GROUP BY p.post_id ORDER BY likes_count DESC"
  elif sort_by == '날짜 순':
    # TODO: 컬럼이름이 date_time 인가?
    sql += " ORDER BY p.date_time DESC"

  # Execute the constructed SQL query
  with db.cursor() as cursor:
    cursor.execute(sql)
    posts = cursor.fetchall()

  # Return the list of posts as JSON response
  return jsonify({'posts': posts}), 200

# { 
#   file_binary: string, 
#   title: string, 
#   content: string, 
#   category: string 
# }
@app.route('/article/write', methods=['POST'])
def write_article():
  file_binary = request.files.get('file_binary')
  title = request.form.get('title')
  content = request.form.get('content')
  category = request.form.get('category')

  if file_binary:
    # TODO: 경로 지정 해야함
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

# { post_id: string }
@app.route('/article', methods=['GET'])
def get_article():
  post_id = request.args.get('post_id')

  if not post_id:
    return jsonify({'error': 'Missing post_id parameter'}), 400

  # SQL query to fetch article details with view count and like count
  # TODO: 여기 테이블이름 다 이상함 상우가 보낸 테이블 이름보고 한번 참고해봐
  sql = """
    SELECT p.category, p.title, p.content, u.name AS author,
        s.subject_name AS selected_subject, p.date_time,
        COUNT(v.view_id) AS view_count,
        COUNT(pl.id) AS like_count
    FROM Posts p
    LEFT JOIN Users u ON p.user_id = u.user_id
    LEFT JOIN User_Subject us ON p.user_id = us.user_id
    LEFT JOIN Subject s ON us.subject_id = s.subject_id
    LEFT JOIN PostViews v ON p.post_id = v.post_id
    LEFT JOIN PostLike pl ON p.post_id = pl.post_id
    WHERE p.post_id = %s
    GROUP BY p.post_id
  """

  # Execute the SQL query
  with db.cursor() as cursor:
    cursor.execute(sql, (post_id,))
    article = cursor.fetchone()

  if not article:
    return jsonify({'error': 'Post not found'}), 404

  # Return the article details as JSON response
  return jsonify(article), 200

# { post_id: string }
@app.route('/article/delete', methods=['DELETE'])
def delete_articel():
  post_id = request.args.get('post_id')

  if not post_id:
    return jsonify({'error': 'Missing post_id parameter'}), 400
  
  sql = "DELETE FROM Posts WHERE post_id = %s"
  with db.cursor() as cursor:
    cursor.execute(sql, (post_id))

  return Response(status=202)

# { post_id: string, content: post_id }
@app.route('/jinhyeon', methods=["POST"])
def create_comment():
  post_id = request.args.get('post_id')
  content = request.args.get('content')
  user_id = get_user_id_from_session()
  create_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

  sql = "INSERT INTO Comments (post_id, user_id, content, datetime) VALUES (%s, %s, %s, %s)"
  with db.cursor() as cursor:
    cursor.execute(sql, (post_id, user_id, content, create_at))
    db.commit()

  return Response(status=200)

# { post_id: string }
@app.route('/jinhyeon_view', methods=["GET"])
def get_comment():
  user_id = get_user_id_from_session()

  if not user_id:
    return jsonify({'message': 'User not authenticated'}), 401
  
  post_id = request.args.get('post_id')
  sql = """
    SELECT Users.name, Comments.content, Comments.datetime FROM Users
    LEFT JOIN Users ON Users.user_id = Comments.user_id
    WHERE Comments.post_id = %s
  """

  with db.cursor() as cursor:
    cursor.execute(sql, (post_id))
    comments = cursor.fetchall();
  
  return Response(response=jsonify({'comments': comments}), status=200)

# { user_id: string }
@app.route('/profile', methods=["GET"])
def get_profile():
  user_id = get_user_id_from_session()
  if not user_id:
    return jsonify({'message': 'User not authenticated'}), 401
  
  target_user_id = request.args.get("user_id")
  sql = """
    SELECT student_id, name FROM Users WHERE user_id = %s
  """

  with db.cursor() as cursor:
    cursor.execute(sql, (target_user_id))
    user = cursor.fetchone();
  
  return Response(response=jsonify({'user': user}), status= 200)

# 없음
@app.route('/logout', methods=["DELETE"])
def logout():
  user_id = get_user_id_from_session()
  if not user_id:
    return jsonify({'message': 'User not authenticated'}), 401
  
  session.pop(user_id)
  return Response(status=202)

if __name__ == '__main__':
  app.run(debug=True)
