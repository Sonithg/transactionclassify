import pymupdf
import os
import json
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer.aio import DocumentAnalysisClient
from openai import OpenAI
import asyncio
import aiofiles
import logging

# Azure API setup
#credential = AzureKeyCredential("blank")
#endpoint = "blank"
#document_analysis_client = DocumentAnalysisClient(endpoint, credential)

# logging.basicConfig(level=logging.INFO)

# Setup GPT API
client = OpenAI(api_key='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')
assistant = client.beta.assistants.create(
    name="The Accountant",
    description="Master of finding transactions in a document and listing them in a table",
    instructions="You are an accountant that is helping me with finding the financial transactions in a given document",
    model="gpt-4o",
    tools=[{"type": "file_search"}],
    temperature=0.0,
)

async def validate_file(file):
    # Check if file size is within bounds for Azure provider
    fileSize = os.stat(file).st_size
    if fileSize > (50 * 1024 * 1024):
        return False
    
    # Use pymupdf function to check if the file is a valid PDF
    return pymupdf.Document(file).is_pdf

async def ocr(file_id: str):
    ocr_output = None
    try:
        async with aiofiles.open(f"./documents/{file_id}.pdf", "rb") as document:
            document_bytes = await document.read()
            
            document_analysis_client = DocumentAnalysisClient(endpoint=endpoint, credential=credential)
            poller = await document_analysis_client.begin_analyze_document(
                "prebuilt-layout",
                document=document_bytes
            )
            analyze_result = await poller.result()
            ocr_output = analyze_result.to_dict()
    except Exception as e:
        print("Error occured during OCR", e)
    
    return ocr_output


# try get rid of this function - it doesnt look good here tbh 
# Remove uneeded keys from dicionary
async def trim_pdf(data):
    remove_keys = ["bounding_regions", "kind", "spans"]

    # If the data is a dictionary
    if isinstance(data, dict):
        # Create a new dictionary with keys that are not in keys_to_remove
        new_dict = {}
        for key, value in data.items():
            if key not in remove_keys:
                new_dict[key] = await trim_pdf(value)  # Recursively apply the function to the value
        return new_dict
    
    # If the data is a list
    elif isinstance(data, list):
        # Apply the function to each item in the list
        return [await trim_pdf(item) for item in data]
    
    # If the data is neither a dictionary nor a list, return it as is
    else:
        return data

async def process_pdf(file_id: str):
    full_ocr = await ocr(file_id)

    if full_ocr is not None:
        filtered_ocr = await trim_pdf(full_ocr['tables'])
        json_ocr = json.dumps(filtered_ocr)  
        async with aiofiles.open(f"./processing/{file_id}.json", "w") as f:
            await f.write(json_ocr)

async def process_pdf2(file_id: str):
    full_ocr = await ocr(file_id)

    if full_ocr is not None:        
        filtered_ocr = await trim_pdf(full_ocr['tables'])

        with open(f"./processing/{file_id}.json", "w") as f:
            json.dump(filtered_ocr, f)

        # Upload the user-provided file to OpenAI
        message_file = client.files.create(
            file=open(f"./processing/{file_id}.json", "rb"), purpose="assistants"
        )

        # Create a thread and attach the file to the message
        thread = client.beta.threads.create(
            messages=[
                {
                    "role": "user",
                    "content": "Help me extract data from the bank statement provided. In particular, the transaction history shown in that statement. The transaction history appears as a table that spans several pages and includes columns for the Date, Check Number, Description, Deposits/Credits, Withdrawals/Debits, and Ending Daily Balance. Create a table using this information that contains the date, a human-readable description (such as payment to location and no extra numbers), and the amount (in that order). If it is a withdrawal make it a '-' and if it is a payment incoming put a '+'. Return only the table in JSON format",
                    "attachments": [
                        {"file_id": message_file.id, "tools": [{"type": "file_search"}]}
                    ],
                }
            ]
        )
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread.id, assistant_id=assistant.id
        )
        messages = list(client.beta.threads.messages.list(thread_id=thread.id, run_id=run.id))

        message_content = messages[0].content[0].text
        annotations = message_content.annotations
        citations = []
        json_content = messages['data'][0]['content'][0]['text']['value']

        
        for index, annotation in enumerate(annotations):
            message_content.value = message_content.value.replace(annotation.text, f"[{index}]")
            if file_citation := getattr(annotation, "file_citation", None):
                cited_file = client.files.retrieve(file_citation.file_id)
                citations.append(f"[{index}] {cited_file.filename}")
        
        combined_output = f"{message_content.value}\n\n" + "\n".join(citations)
        with open(f"./processed/{file_id}.json", "w") as f:
            f.write(combined_output)

        # Clean up
        os.remove(f"./processing/{file_id}.json")
        os.remove(f"./documents/{file_id}.pdf")