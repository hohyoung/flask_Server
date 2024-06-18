from bs4 import BeautifulSoup
from pymongo import MongoClient
from datetime import datetime, timedelta
import cloudscraper
import re

# MongoDB 설정
client = MongoClient("mongodb://localhost:27017")
db = client['stock_data']
collection_news = db.news
collection_comments = db.comments
collection_investing = db.investing_comments

# 인덱스 설정 (이미 설정되어 있다면 필요 없음)
collection_news.create_index('종목코드')
collection_comments.create_index('종목코드')
collection_investing.create_index('종목코드')

# HTML 정보 가져오기 및 headers 세팅
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.150 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9'
}

def is_valid_text(text):
    # 한글만 포함된 경우 유효
    return bool(re.search('[가-힣]', text))

def delete_comments(stock_code, collection):
    collection.delete_many({'종목코드': stock_code})

def fetch_url(url):
    scraper = cloudscraper.create_scraper()
    response = scraper.get(url, headers=headers)
    response.raise_for_status()
    response.encoding = 'utf-8'
    return response.content

def crawl_news(stock_code):
    try:
        today = datetime.now().strftime('%Y.%m.%d')
        date_threshold = datetime.now() - timedelta(days=5)
        delete_comments(stock_code, collection_news)

        page = 1
        unique_news = set()
        while True:
            news_url = f'https://finance.naver.com/item/news_news.nhn?code={stock_code}&page={page}'
            source_code = fetch_url(news_url)
            if source_code is None:
                break
            html = BeautifulSoup(source_code, "lxml")
            titles = html.select('.title')
            title_result = [title.get_text().strip() for title in titles]
            links = html.select('.title a')
            link_result = ['https://finance.naver.com' + link['href'] for link in links]
            dates = html.select('.date')
            date_result = [date.get_text().strip() for date in dates]

            data_exists = False
            for i in range(len(title_result)):
                news_date = datetime.strptime(date_result[i], '%Y.%m.%d %H:%M')
                if news_date >= date_threshold and is_valid_text(title_result[i]):
                    record = {
                        '종목코드': stock_code,
                        '날짜': date_result[i],
                        '내용': title_result[i]
                    }
                    if title_result[i] not in unique_news:  # 중복 뉴스 필터링

                        collection_news.insert_one(record)
                        unique_news.add(title_result[i])
                        data_exists = True

            if not data_exists:
                break
            page += 1
    except Exception as e:
        print(f"An error occurred in crawl_news: {e}")

def crawl_comments(stock_code):
    try:
        date_threshold = datetime.now() - timedelta(days=3)
        delete_comments(stock_code, collection_comments)

        page_num = 1
        unique_comments = set()
        while True:
            comment_url = f"https://finance.naver.com/item/board.naver?code={stock_code}&page={page_num}"
            source_code = fetch_url(comment_url)
            if source_code is None:
                break
            soup = BeautifulSoup(source_code, 'html.parser')
            table = soup.find('table', {'class': 'type2'})
            if not table:
                print(f"No table found on page {page_num} for stock {stock_code}")
                break
            tb = table.select('tbody > tr')
            if not tb:
                break

            data_exists = False
            for i in range(2, len(tb)):
                if len(tb[i].select('td > span')) > 0:
                    date = datetime.strptime(tb[i].select('td > span')[0].text, '%Y.%m.%d %H:%M')
                    if date >= date_threshold:
                        comment = tb[i].select('td.title > a')[0]['title']
                        pos = tb[i].select('td > strong')[0].text
                        neg = tb[i].select('td > strong')[1].text
                        if is_valid_text(comment):
                            record = {
                                '종목코드': stock_code,
                                '내용': comment,
                                '날짜': date.strftime('%Y.%m.%d %H:%M'),
                                '공감': pos,
                                '비공감': neg
                            }
                            if comment not in unique_comments:  # 중복 댓글 필터링

                                collection_comments.insert_one(record)
                                unique_comments.add(comment)
                                data_exists = True

            if not data_exists:
                break
            page_num += 1
    except Exception as e:
        print(f"An error occurred in crawl_comments: {e}")

def get_url_info(url):
    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, headers=headers)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return BeautifulSoup(response.content, 'lxml')
    except Exception as e:
        print(f"An error occurred in get_url_info: {e}")
        return None

def get_discussion_url(company_code):
    try:
        base_url = 'https://kr.investing.com/search/?q='
        search_url = f"{base_url}{company_code}"
        soup = get_url_info(search_url)
        if soup is None:
            return None
        first_result = soup.select_one('a.js-inner-all-results-quote-item')
        if first_result:
            href = first_result['href']
            discussion_url = f"https://kr.investing.com{href}-commentary"

            return discussion_url
        else:
            print(f"Failed to find discussion URL for {company_code}")
            return None
    except Exception as e:
        print(f"An error occurred in get_discussion_url: {e}")
        return None

def crawl_investing(stock_code):
    try:
        today = datetime.now()
        date_threshold = today - timedelta(days=10)
        delete_comments(stock_code, collection_investing)
        discussion_url = get_discussion_url(stock_code)
        if not discussion_url:
            print(f"Failed to find discussion URL for {stock_code}")
            return

        page = 1
        scraped_comments = set()
        while True:
            url = f"{discussion_url}/{page}"
            soup = get_url_info(url)
            if soup is None:
                break
            comments = soup.select('div.break-words.leading-5')
            dates = soup.select('time')

            if not comments or not dates:
                break

            data_exists = False
            for comment, date in zip(comments, dates):
                comment_text = comment.get_text().strip()
                comment_date = datetime.strptime(date['datetime'], '%Y-%m-%dT%H:%M:%S.%fZ')

                if comment_text in scraped_comments or not is_valid_text(comment_text):
                    continue

                if comment_date >= date_threshold:
                    record = {
                        '종목코드': stock_code,
                        '내용': comment_text,
                        '날짜': comment_date.strftime('%Y-%m-%d %H:%M:%S'),
                        '링크': url
                    }
                    if comment_text not in scraped_comments:  # 중복 댓글 필터링

                        collection_investing.insert_one(record)
                        scraped_comments.add(comment_text)
                        data_exists = True

            if not data_exists:
                break
            page += 1
    except Exception as e:
        print(f"An error occurred in crawl_investing: {e}")
