from bs4 import BeautifulSoup
import logfire

def parse_html(file_path:str):
    "Parses HTML content using Beautiful Soup, Cleans script, styles, extracts readable text for RAG"

    with logfire.span("HTML Parsing", filename=file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content=f.read()

            soup=BeautifulSoup(content, "html.parser")

            # Removing Junk(Scripts, Styles, Metadata)
            for script in soup(["script", "style", "meta", "noscript"]):
                script.decompose()
            
            # Extract text
            text=soup.get_text(separator="\n")

            # Clean whitespace.
            #
            # NOTE the double space in split("  "). This is the standard
            # BeautifulSoup whitespace-cleanup idiom, and splitting on a SINGLE
            # space instead breaks it completely: every word becomes its own
            # element and the join below puts each on its own line. That is
            # exactly what happened here -- both HTML documents were indexed at
            # ~5 characters per line ("A\nHands-On\nGuide\nto\nKubernetes"),
            # against ~30-55 for the correctly parsed formats.
            #
            # The damage is quiet: the text is all still present, so nothing
            # errors and the character count looks right. It only shows up if
            # you measure line length, or read a retrieved passage.
            lines = (line.strip() for line in text.splitlines())
            phrases = (phrase.strip() for line in lines for phrase in line.split("  "))
            text_clean = "\n".join(p for p in phrases if p)

            return text_clean
        
        except Exception as e:
            logfire.error(f"HTML Parse Failed: {e}")
            raise e