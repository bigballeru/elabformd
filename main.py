import requests
import pandas as pd
import streamlit as st
from openai import OpenAI
from bs4 import BeautifulSoup

# Constants
URL = "https://efts.sec.gov/LATEST/search-index"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Origin': 'https://www.sec.gov',
    'Referer': 'https://www.sec.gov/'
}

# Sidebar for the chatbot interface
with st.sidebar:
    with st.popover("OpenAI API Key", help = "Please insert you API Key to use the chatbot"):
        st.header("💬 ChatGPT")
        openai_api_key = st.text_input("OpenAI API Key", key="chatbot_api_key", type="password")

    # Use a separate session state key for chatbot messages
    if "chatbot_messages" not in st.session_state:
        st.session_state["chatbot_messages"] = [{"role": "assistant", "content": "Ask me anything about the Form D filings"}]

    for msg in st.session_state["chatbot_messages"]:
        st.chat_message(msg["role"]).write(msg["content"])

    if prompt := st.chat_input():
        if not openai_api_key:
            st.info("Please add your OpenAI API key to continue.")
            st.stop()

        client = OpenAI(api_key=openai_api_key)
        st.session_state["chatbot_messages"].append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)
        response = client.chat.completions.create(model="gpt-4o", messages=st.session_state["chatbot_messages"])
        msg = response.choices[0].message.content
        st.session_state["chatbot_messages"].append({"role": "assistant", "content": msg})
        st.chat_message("assistant").write(msg)

def fetch_sec_filings(start_date, end_date):
    """Fetch SEC filings between two dates."""
    params = {'dateRange': 'custom', 'startdt': start_date, 'enddt': end_date, 'forms': 'D'}
    try:
        response = requests.get(URL, headers=HEADERS, params=params)
        response.raise_for_status()  # Raises a HTTPError for bad responses
        return clean_up(response.json())  # Assuming the response is JSON
    except requests.RequestException as e:
        st.error(f"Request failed: {e}")
        return None

def clean_up(response):
    results = []
    # Ensure the path to the data is correct and exists
    if 'hits' in response and 'hits' in response['hits']:
        for item in response['hits']['hits']:
            source = item.get("_source", {})
            # Generate Edgar links if 'ciks' and 'adsh' are available
            if 'ciks' in source and source.get('adsh'):
                adsh_cleaned = source["adsh"].replace('-', '')  # Remove hyphens from ADSH
                edgar_links = ', '.join(
                    [f'<a href="https://www.sec.gov/Archives/edgar/data/{cik.lstrip("0")}/{adsh_cleaned}/xslFormDX01/primary_doc.xml" target="_blank">Link</a>' 
                     for cik in source["ciks"]]
                )
            else:
                edgar_links = "No links available"

            # Apply transformations to CIK and ADSH in the result dictionary too if needed
            cik_cleaned = [cik.lstrip('0') for cik in source.get("ciks", [])]

            result = {
                "CIK": ', '.join(cik_cleaned),
                "Company Name": ', '.join(source.get("display_names", [])),
                "File Date": source.get("file_date", "Unknown"),
                "Business Location(s)": ', '.join(source.get("biz_locations", [])),
                "ADSH": source.get("adsh", "N/A").replace('-', ''),  # Clean ADSH displayed in results
                "Edgar": edgar_links
            }
            results.append(result)

    add_and_edit(results)

    for result in results:
        result.pop('CIK', None)  # Remove CIK safely
        result.pop('ADSH', None)  # Remove ADSH safely

    # TOTALLY OPTIONAL TO CLEAN UP DATA
    filtered_results = [entry for entry in results if entry.get("Related Persons")]
    results = filtered_results  # If you want to update the original list

    return results

def main():
    """Main function to run the Streamlit app."""
    st.title('Daily Form D Filings')

    # Custom CSS to center text in the table
    center_css = """
    <style>
    th, td {
        text-align: center;
    }
    </style>
    """
    st.markdown(center_css, unsafe_allow_html=True)

    # Use a separate session state key for form submissions
    if "filing_results" not in st.session_state:
        st.session_state["filing_results"] = None

    start_date = st.date_input("Start Date")
    end_date = st.date_input("End Date")
    if st.button("Check for Filings"):
        filings = fetch_sec_filings(start_date, end_date)
        if filings:
            df = pd.DataFrame(filings)
            st.session_state["filing_results"] = df
            # Render the dataframe as HTML to allow styling and make links clickable
            st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.write("No filings found or an error occurred.")
    elif st.session_state["filing_results"] is not None:
        # Display existing results if the form was already run
        st.write(st.session_state["filing_results"].to_html(escape=False, index=False), unsafe_allow_html=True)

def add_and_edit(myResults):
    for company in myResults:
        cikNumNoZeros = company["CIK"].lstrip('0')
        adshNoHyphens = company["ADSH"].replace('-', '')

        newLink = f"https://www.sec.gov/Archives/edgar/data/{cikNumNoZeros}/{adshNoHyphens}/xslFormDX01/primary_doc.xml"

        responseNew = requests.get(newLink, headers=HEADERS)
        
        soup = BeautifulSoup(responseNew.text, 'lxml')

        company["Related Persons"] = ', '.join(extract_related_persons(soup))
        company["Phone Number"] = extract_phone_number(soup)
        offered, raised = extract_offering_amounts(soup)
        company["Total Offering Amount / Amount Raised"] = f"{offered} / {raised}"

def extract_related_persons(soup):
    related_persons = []
    tables = soup.find_all('table', summary="Related Persons")
    for table in tables:
        rows = table.find_all('tr')[1:3]  # Skip header row
        for row in rows:
            cols = row.find_all('td')
            if cols:
                name = " ".join(col.get_text(strip=True) for col in reversed(cols))
                # name = " ".join(col.get_text(strip=True) for col in cols)
                related_persons.append(name)
    return related_persons

def extract_phone_number(soup):
    # Locate section possibly containing the phone number
    section = soup.find('th', string='Phone Number of Issuer')
    if section:
        # Navigate to the parent of the parent row of the 'th'
        row = section.parent.parent
        # Find all 'td' elements in this row
        tds = row.find_all('td')
        # Since 'th' and 'td' elements align, find index of 'th' in its parent and use it to fetch corresponding 'td'
        index = row.find_all('th').index(section)
        if len(tds) > index:
            phone_number = tds[index].get_text(strip=True)
            return phone_number
        else:
            phone_number = tds[-1].get_text(strip=True)
            return phone_number
    return "Not Found"

def extract_offering_amounts(soup):
    # Adjust to accurately find the section containing the offering amounts
    offering_section = soup.find('td', string='Total Offering Amount')
    sold_section = soup.find('td', string='Total Amount Sold')
    if offering_section and sold_section:
        if not offering_section.find_next('td').get_text(strip=True):
            offering_amount_td = soup.find('td', string="Total Offering Amount").find_next_sibling('td')
            x_in_checkbox = offering_amount_td.find_next('span', class_="FormData")
            if x_in_checkbox and x_in_checkbox.text.strip() == "X":
                total_offering_amount = 'Indefinite'
        else:
            total_offering_amount = offering_section.find_next('td').get_text(strip=True)
        total_sold_amount = sold_section.find_next('td').get_text(strip=True)
        return total_offering_amount, total_sold_amount
    return "Not Found", "Not Found"

if __name__ == "__main__":
    main()
