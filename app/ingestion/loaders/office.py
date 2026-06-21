import logfire
from unstructured.partition.auto import partition

def parse_office(file_path:str):
    "Parses office documents (.docx, .pptx) using the Unstructured Library."
    "Unlike PDFs, these formats are structured and lightweight so they are processed locally"
    with logfire.span("Office Document Parsing", filename=file_path):
        try:
            # Unstructured automatically detects if it's docx or ppt
            element=partition(filename=file_path)
            full_text="\n".join([str(el) for el in element])

            if not full_text.strip():
                logfire.warning(f"Unstructured returned empty text for {file_path}")
            else:
                logfire.info(f"Succesfully parsed {len(full_text)} characters")
            
            return full_text
        except Exception as e:
            logfire.error(f"Office Parse Failed: {e}")
            raise e