from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
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



def crawl_comments(stock_code, pages):
    # WebDriver 설정
    s = Service(r"C:\Program Files\chromedriver-win64\chromedriver.exe")
    driver = webdriver.Chrome(service=s)

    try:
        for page_num in range(1, pages + 1):
            url = f"https://finance.naver.com/item/board.naver?code={stock_code}&page={page_num}"
            driver.get(url)

            # 페이지가 로드될 때까지 요소가 나타날 때까지 기다립니다.
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'table.type2')))

            # 현재 페이지의 HTML 가져오기
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
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

    except Exception as e:
        print(f"예외가 발생했습니다: {e}")
    finally:
        driver.quit()
