from flask import Flask, jsonify
import requests
from pymongo import MongoClient
import comments_crawler
from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer

app = Flask(__name__)

API_URL = "https://naveropenapi.apigw.ntruss.com/sentiment-analysis/v1/analyze"
CLIENT_ID = "xxx"
CLIENT_SECRET = "xxx"


# MongoDB 설정
client = MongoClient("mongodb://localhost:27017")
db = client['stock_data']
collection_news = db.news
collection_comments = db.comments
collection_investing = db.investing_comments

#크롤링 실행 함수
def crawlingWithStackCode(code):
    comments_crawler.crawl_comments(code)
    comments_crawler.crawl_news(code)
    comments_crawler.crawl_investing(code)

#댓글 필터링 함수
def filteringComments(code, collection, check_empathy=False):
    if check_empathy:
        documents = collection.find({'종목코드': code}, {'내용': 1, '공감': 1, '비공감': 1, '_id': 0})
    else:
        documents = collection.find({'종목코드': code}, {'내용': 1, '_id': 0})

    trash_keywords = ['국힘', '정의당', '민주당', '석열', '윤통', '국민의힘', '만진당', '노무현', '김건희', '예수', '문재인', '찢재', '재명', '2찍', '박정희']
    filtered_documents = []
    last_content = ''

    for doc in documents:
        content = doc.get('내용', '').strip()  # 앞뒤 공백 제거

        # 중복 내용 필터링
        if content == last_content:
            continue  # 이전 내용과 동일한 경우 건너뜀


        if check_empathy:

            # # 키워드 필터링
            if any(keyword in content for keyword in trash_keywords):
                continue  # 불필요한 키워드가 포함된 내용은 건너뜀
            empathy = int(doc.get('공감', 0))
            antipathy = int(doc.get('비공감', 0))
            # 공감/비공감 비율 필터링
            if antipathy > 0 and empathy / (antipathy + 1) < 1:
                continue  # 비공감이 공감보다 많거나 비슷한 경우 제외

        filtered_documents.append(doc)
        last_content = content


    return filtered_documents


#긍부정 평가 함수
def analysisComments(documents):
    results = []
    comments = []

    headers = {
        'X-NCP-APIGW-API-KEY-ID': CLIENT_ID,
        'X-NCP-APIGW-API-KEY': CLIENT_SECRET,
        'Content-Type': 'application/json'
    }

    # 댓글을 25개씩 묶어 처리
    for doc in documents:
        content = doc.get('내용', '')

        # 대괄호 내용 제거
        while '[' in content:
            start_index = content.find('[')
            end_index = content.find(']', start_index + 1)
            if start_index != -1 and end_index != -1:
                # 대괄호와 내용 제거
                content = content[:start_index] + content[end_index + 1:]
            else:
                # 만약 닫는 대괄호가 없다면, 열린 대괄호 이후 모든 내용 제거
                content = content[:start_index]
                break

        # 문장 종결 부호 추가
        if not content.endswith(('.', '!', '?')):
            content += '.'

        content += ' '
        comments.append(content)

        if len(comments) == 25:
            results.extend(process_comments_batch(comments, headers))
            comments = []  # Reset the batch after processing

    # 처리 후 남은 댓글이 있다면 요청 보내기
    if comments:
        results.extend(process_comments_batch(comments, headers))

    return results

# 긍부정 분석 후 댓글 리스트 만드는 함수 [[내용,감정],[내용,감정]....]
def process_comments_batch(comments, headers):
    text = ' '.join(comments)
    payload = {'content': text}
    response = requests.post(API_URL, headers=headers, json=payload)
    batch_results = []

    if response.status_code == 200:
        json_response = response.json()
        for sentence in json_response['sentences']:
            sentiment = sentence['sentiment']
            batch_results.append([sentence['content'], sentiment])  # 구분자 제거 후 추가

    return batch_results


#특정한 감정의 글들을 모음
def extract_keywords_for_sentiment(comments, sentiment, top_n, exclude_keywords):
    if not comments:
        return []

    # 감정에 따른 코멘트 필터링
    filtered_comments = [comment for comment, s in comments if s == sentiment]

    korean_stopwords = load_stopwords('stopword.txt')
    # TF-IDF Vectorizer 객체 생성, 한국어 불용어 리스트 사용
    tfidf = TfidfVectorizer(max_features=500, stop_words=korean_stopwords)

    # 문장 리스트를 TF-IDF 행렬로 변환
    tfidf_matrix = tfidf.fit_transform(filtered_comments)

    # 각 단어의 TF-IDF 점수를 가져와서 정렬
    feature_array = tfidf.get_feature_names_out()
    tfidf_sorting = tfidf_matrix.sum(axis=0).A1.argsort()[::-1]

    # 상위 n개의 키워드를 추출, 이미 추출된 키워드 제외
    top_keywords = [feature_array[i] for i in tfidf_sorting if feature_array[i] not in exclude_keywords][:top_n]

    return top_keywords

#모아진 감정의 글에서 키워드를 추출
def extract_keywords(comments, top_n):
    if not comments:
        return []

    korean_stopwords = load_stopwords('stopword.txt')
    # TF-IDF Vectorizer 객체 생성, 한국어 불용어 리스트 사용
    tfidf = TfidfVectorizer(max_features=500, stop_words=korean_stopwords)

    # 문장 리스트를 TF-IDF 행렬로 변환
    tfidf_matrix = tfidf.fit_transform(comments)

    # 각 단어의 TF-IDF 점수를 가져와서 정렬
    feature_array = tfidf.get_feature_names_out()
    tfidf_sorting = tfidf_matrix.sum(axis=0).A1.argsort()[::-1]

    # 상위 n개의 키워드를 추출
    top_keywords = [feature_array[i] for i in tfidf_sorting[:top_n]]

    return top_keywords

#감정 평가를 기준으로 점수를 산출
def rankData(comments_results, news_results, investing_results):
    # 데이터 소스 별 가중치 설정
    weights = {
        'comments': {'weight': 1, 'positive': 1.2, 'neutral': 1, 'negative': 0.8},
        'news': {'weight': 4, 'positive': 1.3, 'neutral': 1, 'negative': 0.7},
        'investing': {'weight': 2, 'positive': 1.2, 'neutral': 1, 'negative': 0.7}
    }

    # 최소 및 최대 점수 계산
    min_score = 0
    max_score = 0

    # 각 결과의 가능한 최소 및 최대 점수 계산
    for key, values in weights.items():
        min_sentiment_weight = min(values['positive'], values['neutral'], values['negative'])
        max_sentiment_weight = max(values['positive'], values['neutral'], values['negative'])
        min_score += len(eval(key + '_results')) * values['weight'] * min_sentiment_weight
        max_score += len(eval(key + '_results')) * values['weight'] * max_sentiment_weight

    total_score = 0

    # 각 데이터 소스를 순회하며 점수 계산
    for result, source in [(comments_results, 'comments'), (news_results, 'news'), (investing_results, 'investing')]:
        source_weight = weights[source]["weight"]
        for content, sentiment in result:
            sentiment_weight = weights[source][sentiment]
            total_score += source_weight * sentiment_weight

    # 점수 정규화 (0에서 100 사이)
    normalized_score = int(100 * (total_score - min_score) / (max_score - min_score)) if max_score != min_score else 0

    return normalized_score


# 각 결과에 대해 감정의 수를 세는 함수
def count_sentiments(results):
    sentiment_counter = Counter([result[1] for result in results])
    return {'positive': sentiment_counter['positive'], 'neutral': sentiment_counter['neutral'], 'negative': sentiment_counter['negative']}

# 파일을 읽고 각 줄을 리스트로 변환하는 함수
def load_stopwords(filename):
    with open(filename, 'r', encoding='utf-8') as file:
        stopwords = [line.strip() for line in file.readlines()]
    return stopwords




@app.route('/')
def mainText():
    return "Hello"

@app.route('/favicon.ico')
def favicon():
    return '', 204  # 내용이 없는 응답 반환



@app.route('/<title>', methods=['GET'])
def analysis(title):
    #종목코드를 바탕으로 크롤링 진행
    crawlingWithStackCode(title)

    #DB를 읽어와 쓸모있는 댓글 리스트를 구성
     # comments 컬렉션은 공감/비공감 비율을 확인
    comments_data = filteringComments(title, collection_comments, check_empathy=True)
     # news와 investing 컬렉션은 기본 필터링만 수행
    news_data = filteringComments(title, collection_news)
    investing_data = filteringComments(title, collection_investing)

    # 분석 결과를 각각 처리
    comments_results = analysisComments(comments_data)
    news_results = analysisComments(news_data)
    investing_results = analysisComments(investing_data)

    all_results = news_results + investing_results

    # 감정별 키워드 추출

    general_keywords = extract_keywords([comment for comment, _ in all_results], 10)
    news_keywords = extract_keywords([comment for comment, _ in news_results], 10)

    keywords_positive = extract_keywords_for_sentiment(all_results, 'positive', 5, news_keywords)
    keywords_neutral = extract_keywords_for_sentiment(all_results, 'neutral', 5, news_keywords)
    keywords_negative = extract_keywords_for_sentiment(all_results, 'negative', 5, news_keywords)

    # 분석 내용을 바탕으로 점수 산출
    total_score = rankData(comments_results, news_results, investing_results)

    # 결과에서 감정 개수 계산
    comments_sentiments = count_sentiments(comments_results)
    news_sentiments = count_sentiments(news_results)
    investing_sentiments = count_sentiments(investing_results)

    if total_score < 20:
        total_sentiment = 'negative'
    elif total_score < 50:
        total_sentiment = 'neutral'
    else:
        total_sentiment = 'positive'

    return jsonify({
        'total_sentiment': total_sentiment,
        'sentiment_count': {
            'positive': {
                'comments': comments_sentiments['positive'],
                'news': news_sentiments['positive'],
                'investing': investing_sentiments['positive']
            },
            'neutral': {
                'comments': comments_sentiments['neutral'],
                'news': news_sentiments['neutral'],
                'investing': investing_sentiments['neutral']
            },
            'negative': {
                'comments': comments_sentiments['negative'],
                'news': news_sentiments['negative'],
                'investing': investing_sentiments['negative']
            }
        },
        'total_score': total_score,
        'keywords': {
            'positive': keywords_positive,
            'neutral': keywords_neutral,
            'negative': keywords_negative,
            'total': general_keywords,
            'news': news_keywords
        }
    })
def main():
    app.run(host='localhost', debug=False, port=5000)

if __name__ == '__main__':
    main()