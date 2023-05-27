import requests
from bs4 import BeautifulSoup
import urllib.parse
import time
import random

def crawl_indeed(search_terms, location, num_pages):
    # Encode the search terms and location for the URL
    encoded_search_terms = urllib.parse.quote(search_terms)
    encoded_location = urllib.parse.quote(location)

    # Crawl multiple pages
    for page in range(1, num_pages + 1):
        # Construct the search URL with pagination
        url = f'https://www.indeed.com/jobs?q={encoded_search_terms}&l={encoded_location}&radius=50&start={page * 10}'

        # Send a GET request to the webpage
        response = requests.get(url)

        # Check if the request was successful
        if response.status_code == 200:
            # Parse the HTML content using BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')

            # Extract job URLs from the search results
            job_links = soup.find_all('a', {'class': 'tapItem'})

            # Print the extracted job URLs
            for link in job_links:
                job_url = 'https://www.indeed.com' + link.get('href')
                print(job_url)

            # Generate a random delay between 30 seconds and 4 minutes
            delay = random.randint(30, 240)
            print(f"Delaying for {delay} seconds...")
            time.sleep(delay)
        else:
            print("Failed to retrieve the webpage. Error:", response.status_code)

# Example usage: crawl job URLs from indeed.com
search_terms = "systems administrator, server engineer, cloud engineer, security engineer"
location = "55801"  # Replace with the desired location
num_pages = 5  # Number of pages to crawl
crawl_indeed(search_terms, location, num_pages)