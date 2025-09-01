import streamlit as st
import sqlite3
import json
from openai import OpenAI
import re
from datetime import datetime

# Initialize OpenAI client
client = OpenAI(api_key="")

# Database setup - simplified for chat history
conn = sqlite3.connect('chats.db', check_same_thread=False)
conn.execute('''
    CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        conversation_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()

# Define tools
tools = [
    {
        "type": "web_search_preview"
    },
    {
        "type": "code_interpreter",
        "container": {
            "type": "auto"
        }
    },
    {
        "type": "function",
        "name": "generate_image",
        "description": "Generate an image using DALL-E 3 based on a prompt.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The detailed prompt for generating the image."
                }
            },
            "required": ["prompt"],
            "additionalProperties": False
        },
        "strict": True
    }
]

model = "gpt-4o"
system_instructions = """
You are a helpful AI assistant with access to multiple tools:
1. Use web_search_preview for real-time information and current events
2. Use code_interpreter for data analysis, calculations, file processing, and visualizations
3. Use generate_image for creating images when requested

When incorporating image URLs, include them as: 'Generated image: https://example-url.com' with the plain URL.
"""

def get_conversation_messages(conversation_id):
    """Retrieve messages from OpenAI conversation"""
    try:
        items_response = client.conversations.items.list(
            conversation_id=conversation_id,
            limit=100,
            order="asc"
        )
        
        messages = []
        if hasattr(items_response, 'data') and items_response.data:
            for item in items_response.data:
                if (hasattr(item, 'type') and item.type == "message" and 
                    hasattr(item, 'role') and item.role in ['user', 'assistant']):
                    
                    content = ""
                    if hasattr(item, 'content') and item.content:
                        for content_item in item.content:
                            if hasattr(content_item, 'type'):
                                if content_item.type == "input_text" and hasattr(content_item, 'text'):
                                    content += content_item.text
                                elif content_item.type == "output_text" and hasattr(content_item, 'text'):
                                    content += content_item.text
                            elif hasattr(content_item, 'text'):
                                content += content_item.text
                    
                    if content:
                        messages.append({"role": item.role, "content": content})
        
        return messages
    except Exception as e:
        return []

def create_new_chat():
    """Create a new chat conversation"""
    try:
        conversation = client.conversations.create()
        
        # Insert into database with placeholder title
        cursor = conn.execute(
            "INSERT INTO chats (title, conversation_id) VALUES (?, ?)", 
            ("New Chat", conversation.id)
        )
        conn.commit()
        
        return cursor.lastrowid, conversation.id
    except Exception as e:
        st.error(f"Error creating chat: {str(e)}")
        return None, None

def update_chat_title(chat_id, title, conversation_id):
    """Update chat title and last message timestamp"""
    try:
        conn.execute(
            "UPDATE chats SET title = ?, last_message_at = CURRENT_TIMESTAMP WHERE id = ?",
            (title, chat_id)
        )
        conn.commit()
    except Exception as e:
        pass

def generate_title(first_message):
    """Generate a title based on first message"""
    try:
        # Simple title generation - take first few words
        words = first_message.strip().split()[:4]
        title = " ".join(words)
        if len(title) > 30:
            title = title[:27] + "..."
        return title if title else "New Chat"
    except:
        return "New Chat"

# Streamlit app
st.set_page_config(page_title="AI Chat", page_icon="💬", layout="wide")

# Initialize session state
if 'current_chat_id' not in st.session_state:
    st.session_state.current_chat_id = None
if 'conversation_id' not in st.session_state:
    st.session_state.conversation_id = None
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'uploaded_file_ids' not in st.session_state:
    st.session_state.uploaded_file_ids = {}
if 'first_message_sent' not in st.session_state:
    st.session_state.first_message_sent = False

# Sidebar for chat history
with st.sidebar:
    st.title("💬 AI Chat")
    
    # New Chat button
    if st.button("+ New Chat", use_container_width=True):
        st.session_state.current_chat_id = None
        st.session_state.conversation_id = None
        st.session_state.messages = []
        st.session_state.uploaded_file_ids = {}
        st.session_state.first_message_sent = False
        st.rerun()
    
    st.divider()
    
    # Chat history
    st.subheader("Chat History")
    chats = conn.execute(
        "SELECT id, title, conversation_id, created_at FROM chats ORDER BY last_message_at DESC"
    ).fetchall()
    
    for chat_id, title, conv_id, created_at in chats:
        # Highlight current chat
        if st.session_state.current_chat_id == chat_id:
            st.markdown(f"**🔹 {title}**")
        else:
            if st.button(title, key=f"chat_{chat_id}"):
                st.session_state.current_chat_id = chat_id
                st.session_state.conversation_id = conv_id
                st.session_state.messages = get_conversation_messages(conv_id)
                st.session_state.uploaded_file_ids = {}  # Reset files for new chat
                st.session_state.first_message_sent = True
                st.rerun()
    
    st.divider()
    
    # File upload section
    st.subheader("📁 Upload Files")
    uploaded_files = st.file_uploader(
        "Upload files for analysis", 
        accept_multiple_files=True,
        type=['pdf', 'txt', 'docx', 'md', 'json', 'csv', 'xlsx', 'py']
    )
    
    if uploaded_files:
        for uploaded_file in uploaded_files:
            if uploaded_file.name not in st.session_state.uploaded_file_ids:
                try:
                    with st.spinner(f"Uploading {uploaded_file.name}..."):
                        openai_file = client.files.create(
                            file=(uploaded_file.name, uploaded_file.read(), uploaded_file.type),
                            purpose="assistants"
                        )
                        st.session_state.uploaded_file_ids[uploaded_file.name] = openai_file.id
                except Exception as e:
                    st.error(f"Error uploading {uploaded_file.name}")
        
        if st.session_state.uploaded_file_ids:
            st.success(f"✅ {len(st.session_state.uploaded_file_ids)} files uploaded")

# Main chat interface
st.title("AI Assistant")

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "Generated image: " in message["content"]:
            post_split = message["content"].split("Generated image: ", 1)
            if len(post_split) > 1:
                image_part = post_split[1].strip()
                url_match = re.search(r'(https?://[^\s\)]+)', image_part)
                if url_match:
                    image_url = url_match.group(1)
                    st.image(image_url)

# Chat input
user_input = st.chat_input("Type your message here...")

if user_input:
    # Create new chat if none exists
    if st.session_state.conversation_id is None:
        chat_id, conv_id = create_new_chat()
        if chat_id and conv_id:
            st.session_state.current_chat_id = chat_id
            st.session_state.conversation_id = conv_id
        else:
            st.error("Failed to create new chat")
            st.stop()
    
    # Add user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
    
    # Generate title from first message
    if not st.session_state.first_message_sent:
        title = generate_title(user_input)
        update_chat_title(st.session_state.current_chat_id, title, st.session_state.conversation_id)
        st.session_state.first_message_sent = True
    
    with st.spinner("Thinking..."):
        try:
            # Prepare tools with file IDs if files are uploaded
            tools_with_files = tools.copy()
            if st.session_state.uploaded_file_ids:
                file_ids = list(st.session_state.uploaded_file_ids.values())
                for tool in tools_with_files:
                    if tool.get("type") == "code_interpreter":
                        tool["container"] = {
                            "type": "auto",
                            "file_ids": file_ids
                        }
                        break
            
            # Create response
            response = client.responses.create(
                model=model,
                tools=tools_with_files,
                instructions=system_instructions,
                conversation=st.session_state.conversation_id,
                input=[{"role": "user", "content": user_input}]
            )
            
            # Handle tool calls loop
            while True:
                tool_calls = []
                if hasattr(response, 'output') and response.output:
                    for out in response.output:
                        if hasattr(out, 'type') and out.type == "function_call":
                            tool_calls.append(out)
                
                if not tool_calls:
                    break
                
                tool_outputs = []
                for tool_call in tool_calls:
                    tool_name = getattr(tool_call, 'name', None) or getattr(tool_call, 'function', {}).get('name', None)
                    tool_arguments = getattr(tool_call, 'arguments', None) or getattr(tool_call, 'function', {}).get('arguments', None)
                    
                    call_id = None
                    for attr in ['call_id', 'id', 'tool_call_id']:
                        if hasattr(tool_call, attr):
                            call_id = getattr(tool_call, attr)
                            break
                    
                    if not call_id:
                        call_id = f"call_{len(tool_outputs)}"
                    
                    if tool_name == "generate_image":
                        if isinstance(tool_arguments, str):
                            args = json.loads(tool_arguments)
                        else:
                            args = tool_arguments
                        
                        prompt = args["prompt"]
                        img_response = client.images.generate(
                            model="dall-e-3",
                            prompt=prompt,
                            n=1,
                            size="1024x1024"
                        )
                        image_url = img_response.data[0].url
                        tool_outputs.append({
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": f"Generated image: {image_url}"
                        })
                
                if tool_outputs:
                    response = client.responses.create(
                        model=model,
                        conversation=st.session_state.conversation_id,
                        input=tool_outputs
                    )
                else:
                    break
            
            # Extract assistant content
            assistant_content = ""
            if hasattr(response, 'output_text') and response.output_text:
                assistant_content = response.output_text
            elif hasattr(response, 'output') and response.output:
                for out in response.output:
                    if hasattr(out, 'content'):
                        if isinstance(out.content, str):
                            assistant_content += out.content
                        elif hasattr(out.content, 'text'):
                            assistant_content += out.content.text
                        elif isinstance(out.content, list) and len(out.content) > 0:
                            if hasattr(out.content[0], 'text'):
                                assistant_content += out.content[0].text
                            elif isinstance(out.content[0], str):
                                assistant_content += out.content[0]
            
            if not assistant_content:
                assistant_content = "I'm sorry, I couldn't generate a response."
            
            # Add assistant response
            st.session_state.messages.append({"role": "assistant", "content": assistant_content})
            with st.chat_message("assistant"):
                st.markdown(assistant_content)
                if "Generated image: " in assistant_content:
                    post_split = assistant_content.split("Generated image: ", 1)
                    if len(post_split) > 1:
                        image_part = post_split[1].strip()
                        url_match = re.search(r'(https?://[^\s\)]+)', image_part)
                        if url_match:
                            image_url = url_match.group(1)
                            st.image(image_url)
            
            # Update chat timestamp
            if st.session_state.current_chat_id:
                conn.execute(
                    "UPDATE chats SET last_message_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (st.session_state.current_chat_id,)
                )
                conn.commit()
        
        except Exception as e:
            st.error(f"Error: {str(e)}")
