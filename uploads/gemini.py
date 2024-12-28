"""
**Get Answers and Generate Content with Gemini (Google AI)**

> `{i}gemini` (query)

**• Usage:**
*   `{i}gemini <prompt>`: Text response.
*   `{i}gemini -c`: Clears the current chat history.

*   `GEMINI_API` required: `.setdb GEMINI_API <your_api_key>`
"""
import aiohttp
from io import BytesIO
import logging
import base64
import os
import mimetypes
import PyPDF2
from docx import Document
from .. import LOGS, ultroid_cmd, udB

CHAT_HISTORY = {}

class GeminiAI:
    def __init__(self, api_key, model_name="gemini-1.5-flash"):
        self.api_key = api_key
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"
        self.model_name = model_name

    async def text2text(self, prompt, media_data=None, mime_type=None):
        headers = {"Content-Type": "application/json"}
        parts = [{"text": prompt}]
        if media_data and mime_type:
            parts.append({"inlineData": {"mimeType": mime_type, "data": media_data}})
        payload = {"contents": [{"parts": parts}]}
        params = {"key": self.api_key}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/{self.model_name}:generateContent", headers=headers, params=params, json=payload) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "No Content")
        except Exception as e:
            LOGS.error(f"Gemini API Error: {e}")
            return f"Error: {e}"

async def get_media_data(event):
    reply = await event.get_reply_message()
    if not reply or not reply.media:
        return None, None
    try:
        file_path = await event.client.download_media(reply, os.path.join('.', "temp_gemini"))
        mime_tuple = mimetypes.guess_type(file_path)
        mime_type = mime_tuple[0] if mime_tuple else None
        if mime_type and mime_type.startswith(("image/", "audio/", "video/")):
            with open(file_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8"), mime_type
        elif file_path.lower().endswith(".pdf"):
           try:
              text = ""
              with open(file_path, 'rb') as pdf_file:
                 pdf_reader = PyPDF2.PdfReader(pdf_file)
                 for page in pdf_reader.pages:
                    text += page.extract_text()
              return base64.b64encode(text.encode()).decode("utf-8"), "text/plain"
           except Exception as e:
             LOGS.error(f"PDF Extraction Error: {e}")
             return None, None
        elif file_path.lower().endswith(".docx"):
           try:
              doc = Document(file_path)
              text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
              return base64.b64encode(text.encode()).decode("utf-8"), "text/plain"
           except Exception as e:
              LOGS.error(f"DOCX Extraction Error: {e}")
              return None, None
        elif file_path.lower().endswith((".log", ".txt", ".py")):
            try:
                with open(file_path, 'r', encoding='utf-8', errors="ignore") as f:
                    text = f.read()
                    if text:
                       return base64.b64encode(text.encode()).decode("utf-8"), "text/plain"
                    else:
                        return None, None
            except Exception as e:
                LOGS.error(f"Log file read error: {e}")
                return None, None
        else:
            try:
                with open(file_path, 'rb') as f:
                   return base64.b64encode(f.read()).decode("utf-8"), mime_type
            except Exception as e:
              LOGS.error(f"Error processing file: {e}")
              return None, None
    except Exception as e:
         LOGS.error(f"Media Error: {e}")
         return None, None
    finally:
      try:
         os.remove(file_path)
      except:
         pass

@ultroid_cmd(pattern="gemini( (.*)|$)")
async def gemini_command(event):
    api_key = udB.get_key("GEMINI_API")
    model = udB.get_key("GEMINI_MODEL") or "gemini-1.5-flash"
    if not api_key:
        return await event.reply("Set GEMINI_API using `.setdb GEMINI_API key`")

    query = event.pattern_match.group(1).strip()
    if query.lower() == "-c":
        CHAT_HISTORY.clear()
        return await event.edit("__Gemini chat history cleared.__")

    reply_msg = await event.get_reply_message()
    if not query and not reply_msg:
        return await event.reply("Provide a query or reply to a message.")
    
    prompt = query if query else reply_msg.text if reply_msg else ""
    
    if not prompt and not await get_media_data(event):
      return await event.edit("Please provide a prompt or a file.")
    
    msg = await event.eor(f"Generating: `{prompt[:128]}...`")
    media_data, mime_type = await get_media_data(event)

    if mime_type == "text/plain" and not prompt and media_data:
        prompt = "Can you help me with this?"
    
    chat_id = event.chat_id
    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []
    CHAT_HISTORY[chat_id].append({"role": "user", "content": prompt})
    gemini = GeminiAI(api_key, model)
    try:
        reply = await gemini.text2text(prompt, media_data, mime_type)
        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": reply})
        if len(reply) + len(prompt) < 4096:
           await msg.edit(f"**Query:**\n`{prompt}`\n\n**Gemini:**\n{reply}", parse_mode="md")
        else:
           with BytesIO(reply.encode()) as file:
               file.name = "gemini.txt"
               await event.client.send_file(event.chat_id, file, caption=f"**Query:**\n`{prompt[:200]}...`",reply_to=event.reply_to_msg_id, thumb=0, parse_mode="md")
           await msg.delete()
    except Exception as e:
       if chat_id in CHAT_HISTORY:
           CHAT_HISTORY[chat_id].pop()
       await msg.edit(f"Error: {e}", parse_mode="md")
       LOGS.exception("Gemini Error")