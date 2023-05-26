#simple web crawler
#joeproit 5-26-2023

import requests
from bs4 import BeautifulSoup

def crawl_webpage(url):
    # Send a GET request to the webpage
    response = requests.get(url)
    
    # Check if the request was successful
    if response.status_code == 200:
        # Parse the HTML content using BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract desired information from the webpage
        # Here's an example of extracting all the links on the page:
        links = soup.find_all('a')
        
        # Print the extracted links
        for link in links:
            print(link.get('href'))
    else:
        print("Failed to retrieve the webpage. Error:", response.status_code)

# Example usage: crawl a webpage
crawl_webpage('https://www.youtube.com')

quit()
