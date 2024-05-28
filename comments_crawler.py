from bs4 import BeautifulSoup
import requests
from pymongo import MongoClient

# MongoDB 설정
client = MongoClient("mongodb://localhost:27017")
db = client['stock_comments']
collection = db.comments4


def delete_comments(stock_code):
    # 해당 종목 코드에 맞는 댓글들 조회
    comments_to_delete = collection.find({'종목코드': stock_code})

    # 조회된 댓글들을 삭제
    for comment in comments_to_delete:
        collection.delete_one({'_id': comment['_id']})



def crawl_comments(stock_code, page):
    # User-Agent 설정
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36'}

    for page_num in range(1, page + 1):
        print(f'================== Page {page_num} is done ==================')
        url = f"https://finance.naver.com/item/board.naver?code={stock_code}&page={page_num}"

        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', {'class': 'type2'})
        tb = table.select('tbody > tr')

        for i in range(2, len(tb)):
            if len(tb[i].select('td > span')) > 0:
                date = tb[i].select('td > span')[0].text
                comment = tb[i].select('td.title > a')[0]['title']
                pos = tb[i].select('td > strong')[0].text
                neg = tb[i].select('td > strong')[1].text
                record = {
                    '종목코드': stock_code,
                    '댓글 내용': comment,
                    '날짜': date,
                    '공감': pos,
                    '비공감': neg
                }

                # MongoDB에 저장
                collection.insert_one(record)

