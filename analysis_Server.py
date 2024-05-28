from flask import Flask, jsonify
import requests
from pymongo import MongoClient
import comments_crawler

app = Flask(__name__)


API_URL = "https://naveropenapi.apigw.ntruss.com/sentiment-analysis/v1/analyze"
CLIENT_ID = "vllvv1kh0i"
CLIENT_SECRET = "xxx"


# MongoDB 클라이언트 설정
client = MongoClient('mongodb://localhost:27017/')  # MongoDB에 연결
db = client['stock_comments']  # 데이터베이스 선택
collection = db['comments4']  # 컬렉션 선택

@app.route('/')
def mainText():
    return "Hello"

@app.route('/favicon.ico')
def favicon():
    return '', 204  # 내용이 없는 응답 반환


@app.route('/<title>', methods=['GET'])
def analysis(title):
    comments_crawler.delete_comments(title)
    comments_crawler.crawl_comments(title, 5)
    documents = collection.find({'종목코드': title}, {'댓글 내용': 1,'공감':1, '비공감': 1, '_id': 0})

    # 감정 카운트 초기화
    sentiment_count = {'positive': 0, 'negative': 0, 'neutral': 0}
    total_points = 0
    comments = []

    for doc in documents:
        comment = doc.get('댓글 내용', '')
        if not comment.endswith('.'):
            comment += '.'

        neg_count = int(doc.get('비공감', 0))

        if neg_count < 3:
            comments.append(comment)


        # 20개 단위로 댓글을 처리
        if len(comments) == 20:
            text = ' '.join(comments)
            headers = {
                'X-NCP-APIGW-API-KEY-ID': CLIENT_ID,
                'X-NCP-APIGW-API-KEY': CLIENT_SECRET,
                'Content-Type': 'application/json'
            }
            payload = {'content': text}
            response = requests.post(API_URL, headers=headers, json=payload)
            if response.status_code == 200:
                json_response = response.json()
                for sentence in json_response['sentences']:
                    sentiment = sentence['sentiment']
                    sentiment_count[sentiment] += 1

            comments = []  # Reset the batch

    # 처리 후 남은 댓글이 있다면 요청 보내기
    if comments:
        text = ' '.join(comments)
        response = requests.post(API_URL, headers={'X-NCP-APIGW-API-KEY-ID': CLIENT_ID, 'X-NCP-APIGW-API-KEY': CLIENT_SECRET, 'Content-Type': 'application/json'}, json={'content': text})
        if response.status_code == 200:
            json_response = response.json()
            for sentence in json_response['sentences']:
                sentiment = sentence['sentiment']
                sentiment_count[sentiment] += 1

    # 감정 점수 계산
    total_points = (sentiment_count['negative'] * 0) + (sentiment_count['neutral'] * 1) + (sentiment_count['positive'] * 2)
    num_sentences = sum(sentiment_count.values())
    average_score = (total_points / num_sentences) * 50 if num_sentences > 0 else 0

    # 최종 감정 평가
    if average_score <= 40:
        total_sentiment = 'negative'
    elif average_score <= 70:
        total_sentiment = 'neutral'
    else:
        total_sentiment = 'positive'

    return jsonify({
        'total_sentiment': total_sentiment,
        'sentiment_count': sentiment_count,
        'total_score': average_score
    })
def main():
    app.run(host='localhost', debug=False, port=5000)

if __name__ == '__main__':
    main()