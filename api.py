from fastapi import FastAPI, File, UploadFile, HTTPException
from uuid import uuid4
import asyncio
from pdf import validate_file, process_pdf
import json
import aiofiles

app = FastAPI()

files = [
    { "file_id": "123", "status": "processing" }
]

@app.post("/process_document")
async def process_document(file: UploadFile = File(...)):
    # Check file type before saving - if not PDF we save resources here by returning error
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="File must be a PDF")

    file_id = str(uuid4())
    try:
        # Save the file
        async with aiofiles.open(f"documents/{file_id}.pdf", 'wb') as out_file:
            content = await file.read()  
            await out_file.write(content)
        
        if await validate_file(f"documents/{file_id}.pdf") == False:
            raise HTTPException(status_code=400, detail="File must be a PDF")

        # figure out if this is even appending to the list
        files.append({ "file_id": file_id, "status": "processing" })
        # Process the PDF asynchronously
        # Is not running async correctly - main func waits for this
        fileProc = asyncio.create_task(process_pdf(file_id))
        # fileProc.add_done_callback(lambda fileProc: updateDB(fileProc, file_id))

        # This should return while async func is still running
        return {
            "status": "success",
            "file_id": file_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_document/{file_id}")
async def get_document(file_id: str):
    print(files)
    for file in files:
        if file["file_id"] == file_id:
            if file["status"] == "processed":
                with open(f"processed/{file_id}.pdf", 'r') as file:
                    data = json.load(file)  
                    file["data"] = data
            return file
    raise HTTPException(status_code=400, detail="File ID does not exist in database!")

async def updateDB(task, file_id):
    for file in files:
        if file['file_id'] == file_id:
           file['status'] = "processed"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)
