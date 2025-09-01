import streamlit as st
import sqlite3
from openai import OpenAI
from datetime import datetime
import json
import uuid
import time
import os
from typing import Optional, Dict, List
import base64
import requests
from io import BytesIO


# Page configuration
st.set_page_config(
    page_title="genie - Messaging Agent",
    page_icon="🤖",
    layout="wide"
)

# Custom CSS for Claude-like UI
st.markdown("""
<style>
    .main > div {
        padding-top: 1rem;
    }
    
    .stChatMessage {
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 1rem;
    }
    
    .stChatMessage[data-testid="chat-message-user"] {
        background-color: #f0f8ff;
        border-left: 4px solid #4a90e2;
    }
    
    .stChatMessage[data-testid="chat-message-assistant"] {
        background-color: #f8f9fa;
        border-left: 4px solid #28a745;
    }
    
    .chat-header {
        text-align: center;
        padding: 2rem 0;
        border-bottom: 1px solid #e1e5e9;
        margin-bottom: 2rem;
    }
    
    .sidebar-info {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 1rem;
    }
    
    .chat-item {
        padding: 0.5rem;
        border-radius: 4px;
        margin-bottom: 0.5rem;
        cursor: pointer;
        border: 1px solid #e1e5e9;
    }
    
    .chat-item:hover {
        background-color: #f0f0f0;
    }
    
    .chat-item.active {
        background-color: #e3f2fd;
        border-color: #4a90e2;
    }
    
    .feature-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 10px;
        margin: 1rem 0;
        text-align: center;
    }
    
    .viral-post-container {
        background: #f8f9fa;
        border: 2px solid #e9ecef;
        border-radius: 10px;
        padding: 1rem;
        margin: 1rem 0;
    }
    
    .image-preview {
        max-width: 100%;
        border-radius: 8px;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

class DatabaseManager:
    """Handles all database operations"""
    
    def __init__(self, db_path="genie_chats.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize SQLite database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table - now stores the single assistant_id per user
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                assistant_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Chats table - removed assistant_id since we use one per user
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                title TEXT,
                thread_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Drop messages table if it exists (no longer needed)
        cursor.execute('DROP TABLE IF EXISTS messages')
        
        conn.commit()
        conn.close()
    
    def create_user(self, user_id: str, assistant_id: str = None):
        """Create a new user with optional assistant_id"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO users (id, assistant_id) VALUES (?, ?)', 
            (user_id, assistant_id)
        )
        conn.commit()
        conn.close()
    
    def update_user_assistant(self, user_id: str, assistant_id: str):
        """Update user's assistant_id"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET assistant_id = ? WHERE id = ?',
            (assistant_id, user_id)
        )
        conn.commit()
        conn.close()
    
    def get_user_assistant(self, user_id: str) -> Optional[str]:
        """Get user's assistant_id"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT assistant_id FROM users WHERE id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    
    def create_chat(self, chat_id: str, user_id: str, title: str, thread_id: str = None):
        """Create a new chat"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO chats (id, user_id, title, thread_id)
            VALUES (?, ?, ?, ?)
        ''', (chat_id, user_id, title, thread_id))
        conn.commit()
        conn.close()
    
    def update_chat(self, chat_id: str, thread_id: str = None, title: str = None):
        """Update chat with thread ID and/or title"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if thread_id:
            updates.append("thread_id = ?")
            params.append(thread_id)
        
        if title:
            updates.append("title = ?")
            params.append(title)
        
        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(chat_id)
            
            query = f"UPDATE chats SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()
        
        conn.close()
    
    def get_user_chats(self, user_id: str) -> List[Dict]:
        """Get all chats for a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, title, created_at, updated_at, thread_id
            FROM chats 
            WHERE user_id = ? 
            ORDER BY updated_at DESC
        ''', (user_id,))
        
        chats = []
        for row in cursor.fetchall():
            chats.append({
                'id': row[0],
                'title': row[1],
                'created_at': row[2],
                'updated_at': row[3],
                'thread_id': row[4]
            })
        
        conn.close()
        return chats
    
    def delete_chat(self, chat_id: str):
        """Delete a chat"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM chats WHERE id = ?', (chat_id,))
        conn.commit()
        conn.close()
    
    def get_chat_details(self, chat_id: str) -> Optional[Dict]:
        """Get chat details including thread ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, title, thread_id, created_at
            FROM chats WHERE id = ?
        ''', (chat_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row[0],
                'title': row[1],
                'thread_id': row[2],
                'created_at': row[3]
            }
        return None

class ZuuriAssistant:
    """Handles OpenAI Assistant operations with DALL-E 3 Standard size only"""
    
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o-mini"
        self.image_model = "dall-e-3"
        # FIXED SIZE - Only Standard 1024x1024
        self.image_size = "1024x1024"
    
    def get_or_create_assistant(self, user_id: str, db: DatabaseManager) -> str:
        """Get existing assistant or create one for the user"""
        # Check if user already has an assistant
        assistant_id = db.get_user_assistant(user_id)
        
        if assistant_id:
            # Verify the assistant still exists
            try:
                self.client.beta.assistants.retrieve(assistant_id)
                return assistant_id
            except:
                # Assistant doesn't exist anymore, create a new one
                pass
        
        # Create new assistant with DALL-E 3 Standard size only
        try:
            assistant = self.client.beta.assistants.create(
                name="genie - Content Creator",
                instructions="""You are **genie**, a friendly, highly creative, and deeply knowledgeable assistant and content creator for Vonza.  
You combine comprehensive expertise in the Vonza platform with broad general knowledge, keen reasoning abilities, imaginative problem-solving skills, and powerful content creation capabilities.

### Core Capabilities
- **Handle tasks**: Support with planning, writing, research, brainstorming, execution, and workflow organization.  
- **Ask me anything**: Respond confidently to business, technical, creative, or general questions.  
- **24/7 creative assistant**: Generate ideas, strategies, content, marketing concepts, design inspiration, and solutions for business growth and creativity.
- **Viral Content Creator**: Create engaging social media posts, viral content, and marketing materials that capture attention and drive engagement.
- **Image Generation Expert**: Generate compelling images for social media posts, marketing materials, and content creation using AI image generation.
- **Email Marketing Specialist**: Craft professional emails, autoresponders, marketing sequences, and customer communications.

### Special Content Creation Features

**VIRAL POST CREATION WORKFLOW:**
When a user requests to create a viral post:
1. if user ask to create a viral post, see the user message if user want an the only generate image with the post otherwise do not not generate image only create viral post content .
2. **Post Structure**: Include hooks, engaging content, relevant hashtags, and clear calls-to-action
3. **Image Prompts**: Create detailed, specific image prompts that align with the post content and current social media trends

**EMAIL CREATION CAPABILITIES:**
- Professional business emails
- Marketing sequences and campaigns  
- Autoresponder series
- Customer service templates
- Sales emails and follow-ups
- Newsletter content
- Personal outreach emails

### What is Vonza?
Vonza is an **all-in-one business platform** designed for creators, entrepreneurs, course builders, coaches, and small businesses. It combines essential tools for building, marketing, and monetizing your online business—all in one place.

**Key features include**:  
- **Commerce**: Create and sell online courses, physical and digital products, and manage communities.
- **Website & Funnels**: Use drag-and-drop tools to build websites, landing pages, sales funnels, and "link-in-bio" pages—no tech required.
- **Marketing Tools**: Built-in email marketing, SMS messaging, CRM for managing leads and pipelines, invoicing, coupons, upsells, and automation.
- **Scheduling & Forms**: Allow customers to book meetings, collect data via forms, and integrate seamlessly with workflows.
- **School & Membership Management**: Power online schools or universities with features like transcript/reporting, membership tiers, community engagement, and content control.
- **Support & Onboarding**: Offers 24/7 support, robust analytics, free trial options, and extensive resources like Vonza University.

### Content Creation Guidelines

**For Viral Posts:**
- Use attention-grabbing hooks in the first line
- Include storytelling elements and emotional triggers
- Add trending hashtags relevant to the niche
- Include clear calls-to-action
- Optimize for platform-specific formats (Instagram, Facebook, LinkedIn, Twitter, TikTok)
- Use current trends and viral formats
- Include engagement questions to boost interaction

**For Images:**
- Create detailed prompts that match current design trends
- Consider brand colors and visual consistency
- Use engaging compositions and eye-catching elements
- Optimize for social media aspect ratios
- Include relevant visual metaphors and symbols

**For Emails:**
- Compelling subject lines with high open rates
- Personalized content based on audience segments
- Clear value propositions and benefits
- Professional formatting with proper structure
- Strong calls-to-action and next steps
- A/B test variations when appropriate

### Main Responsibilities
- Provide accurate, detailed guidance about the Vonza platform and best practices for its features.  
- Create viral social media content with optional AI-generated images
- Craft professional and marketing emails that convert
- Offer creative, practical solutions for business, marketing, content, and organization tasks.  
- Assist with productivity, task planning, workflow improvements, and task execution.  
- Brainstorm and develop brand, marketing, or course content—including strategies, copywriting, design concepts, or promotional ideas.  
- Support branding, storytelling, digital strategy, and community building.  
- When necessary, conduct online searches to fetch the latest information (release notes, integrations, trends, etc.)

### Key Behaviors
- Be helpful, concise, accurate, and creatively engaging.  
- **ALWAYS ask about image inclusion for viral posts before creating**
- Create content that follows current social media trends and best practices
- Provide actionable, results-driven content strategies
- Ask thoughtful clarifying questions when instructions are vague.  
- Deliver actionable advice in clear, step-by-step or creative-option formats.  
- Proactively suggest ideas, improvements, and next steps.  
- Maintain a friendly, professional, confidence-building tone.  
- Remember and leverage conversation context to personalize assistance.  
- Balance **practicality with creative spark**—save time, inspire ideas, and boost effectiveness.

### Areas of Expertise
- Vonza platform (courses, websites, funnels, marketing, community, scheduling, membership, school management)  
- Viral content creation and social media strategy
- AI image generation and visual content creation
- Email marketing and automation sequences
- Creative ideation, branding, and content strategy  
- Business automation and digital workflows  
- Online course creation and marketing  
- Customer communication and engagement tactics  
- Productivity tools and task/project organization

### Content Creation Commands
When users say:

- "Write an email" → Create professional, converting email content
- "Create marketing materials" → Develop comprehensive marketing content with visual elements

### Remember:
You are **genie**—not just a virtual assistant, but a **trusted executive, creative partner, and content creation powerhouse**.  
Your mission:  
- Make the user's work easier and more successful  
- Create viral, engaging content that drives results
- Handle any task or question with creative excellence**

Always prioritize creating content that gets results, engages audiences, and drives business growth.""",
                model=self.model,
                tools=[
                    {"type": "code_interpreter"},
                    {
                        "type": "function",
                        "function": {
                            "name": "generate_image",
                            "description": "Generate an AI image using DALL-E 3 in Standard size (1024x1024) only",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "prompt": {
                                        "type": "string",
                                        "description": "Detailed description of the image to generate (will be created in 1024x1024 square format)"
                                    },
                                    "style": {
                                        "type": "string", 
                                        "description": "Image style (vivid or natural)",
                                        "enum": ["vivid", "natural"],
                                        "default": "vivid"
                                    }
                                },
                                "required": ["prompt"]
                            }
                        }
                    }
                ]
            )
            
            # Save assistant_id for this user
            db.update_user_assistant(user_id, assistant.id)
            return assistant.id
            
        except Exception as e:
            st.error(f"Error creating assistant: {str(e)}")
            return None
    
    def generate_image_with_dalle(self, prompt: str, style: str = "vivid") -> Optional[str]:
        """Generate image using DALL-E 3 - ONLY Standard 1024x1024 size"""
        try:
            response = self.client.images.generate(
                model=self.image_model,
                prompt=prompt,
                size=self.image_size,  # FIXED to 1024x1024
                quality="standard",
                style=style,
                n=1
            )
            
            if response.data:
                return response.data[0].url
            return None
            
        except Exception as e:
            st.error(f"Error generating image: {str(e)}")
            return None
    
    def create_thread(self) -> str:
        """Create a new conversation thread"""
        try:
            thread = self.client.beta.threads.create()
            return thread.id
        except Exception as e:
            st.error(f"Error creating thread: {str(e)}")
            return None
    
    def get_thread_messages(self, thread_id: str) -> List[Dict]:
        """Get all messages from a thread"""
        try:
            messages = self.client.beta.threads.messages.list(
                thread_id=thread_id,
                order="asc"  # Get messages in chronological order
            )
            
            formatted_messages = []
            for msg in messages.data:
                content = ""
                images = []
                
                if msg.content:
                    for content_item in msg.content:
                        if hasattr(content_item, 'text'):
                            content += content_item.text.value
                        elif hasattr(content_item, 'image_file'):
                            # Handle image files if any
                            images.append(content_item.image_file)
                
                message_data = {
                    'role': msg.role,
                    'content': content,
                    'created_at': msg.created_at
                }
                
                if images:
                    message_data['images'] = images
                    
                formatted_messages.append(message_data)
            
            return formatted_messages
            
        except Exception as e:
            st.error(f"Error retrieving messages: {str(e)}")
            return []
    
    def send_message(self, thread_id: str, assistant_id: str, message: str) -> Dict:
        """Send message and get response from assistant with potential image generation"""
        try:
            # Add message to thread
            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message
            )
            
            # Run the assistant
            run = self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id
            )
            
            # Wait for completion with function calling support
            max_wait = 60  # Increased timeout for image generation
            wait_time = 0
            
            while run.status in ['queued', 'in_progress', 'requires_action'] and wait_time < max_wait:
                time.sleep(2)
                wait_time += 2
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
                
                # Handle function calls (image generation)
                if run.status == 'requires_action':
                    tool_calls = run.required_action.submit_tool_outputs.tool_calls
                    tool_outputs = []
                    
                    for tool_call in tool_calls:
                        if tool_call.function.name == "generate_image":
                            # Parse function arguments
                            args = json.loads(tool_call.function.arguments)
                            # ALWAYS use 1024x1024, ignore any size parameter
                            image_url = self.generate_image_with_dalle(
                                args.get('prompt'),
                                args.get('style', 'vivid')
                            )
                            
                            tool_outputs.append({
                                "tool_call_id": tool_call.id,
                                "output": json.dumps({
                                    "image_url": image_url,
                                    "size": "1024x1024",  # Always report standard size
                                    "status": "success" if image_url else "failed"
                                })
                            })
                    
                    # Submit tool outputs
                    run = self.client.beta.threads.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=run.id,
                        tool_outputs=tool_outputs
                    )
            
            if run.status == 'completed':
                # Get the latest messages
                messages = self.client.beta.threads.messages.list(
                    thread_id=thread_id,
                    limit=1
                )
                
                if messages.data:
                    content = messages.data[0].content[0].text.value
                    return {
                        "content": content,
                        "status": "success"
                    }
                else:
                    return {
                        "content": "I apologize, but I didn't receive a proper response. Could you try asking again?",
                        "status": "error"
                    }
            
            elif run.status == 'failed':
                return {
                    "content": f"I encountered an error processing your request. Please try again.",
                    "status": "error"
                }
            
            else:
                return {
                    "content": f"Request timed out. Please try again with a shorter message.",
                    "status": "timeout"
                }
                
        except Exception as e:
            return {
                "content": f"I apologize, but I encountered an error: {str(e)}. Please try again.",
                "status": "error"
            }

def get_or_create_user_id():
    """Get or create a persistent user ID"""
    # Try to get user ID from query params first (for sharing/bookmarking)
    query_params = st.query_params
    if 'user_id' in query_params:
        return query_params['user_id']
    
    # Try to get from session state
    if 'user_id' in st.session_state:
        return st.session_state.user_id
    
    # Create new user ID and persist it
    user_id = str(uuid.uuid4())[:8]
    st.session_state.user_id = user_id
    
    # Set query param to make it persistent across refreshes
    st.query_params['user_id'] = user_id
    
    return user_id

def initialize_session_state():
    """Initialize session state variables"""
    # Get persistent user ID
    user_id = get_or_create_user_id()
    st.session_state.user_id = user_id
    
    if 'current_chat_id' not in st.session_state:
        st.session_state.current_chat_id = None
    
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    
    if 'assistant' not in st.session_state:
        st.session_state.assistant = None
    
    if 'assistant_id' not in st.session_state:
        st.session_state.assistant_id = None
    
    if 'db' not in st.session_state:
        st.session_state.db = DatabaseManager()
        # Create user in database
        st.session_state.db.create_user(st.session_state.user_id)

def create_new_chat(db: DatabaseManager, user_id: str, title: str = None) -> str:
    """Create a new chat"""
    chat_id = str(uuid.uuid4())[:8]
    if not title:
        title = f"Chat {datetime.now().strftime('%m/%d %H:%M')}"
    
    db.create_chat(chat_id, user_id, title)
    return chat_id

def load_chat(db: DatabaseManager, assistant: ZuuriAssistant, chat_id: str):
    """Load chat messages from OpenAI thread"""
    chat_details = db.get_chat_details(chat_id)
    
    if chat_details and chat_details['thread_id']:
        # Fetch messages from OpenAI
        messages = assistant.get_thread_messages(chat_details['thread_id'])
        st.session_state.messages = messages
    else:
        st.session_state.messages = []
    
    st.session_state.current_chat_id = chat_id

def generate_chat_title(first_message: str) -> str:
    """Generate a title from the first message"""
    # Take first 30 characters and add ellipsis if longer
    title = first_message.strip()
    if len(title) > 30:
        title = title[:27] + "..."
    return title

def restore_last_chat(db: DatabaseManager, assistant: ZuuriAssistant, user_id: str):
    """Restore the user's last active chat"""
    if not assistant:
        return
        
    user_chats = db.get_user_chats(user_id)
    if user_chats and not st.session_state.current_chat_id:
        # Load the most recently updated chat
        last_chat = user_chats[0]  # Already ordered by updated_at DESC
        load_chat(db, assistant, last_chat['id'])

def display_content_creation_examples():
    """Display content creation examples and capabilities"""
    st.markdown("### 🚀 Content Creation Superpowers")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        **🔥 Viral Post Creation**
        - "Create a viral post about online courses"
        - "Generate a LinkedIn post for my new business"
        - "Make an Instagram post about productivity"
        - Includes AI image generation (1024×1024)!
        """)
    
    with col2:
        st.markdown("""
        **📧 Email Writing**
        - "Write a welcome email for new customers"
        - "Create a sales email for my course"
        - "Draft a follow-up email sequence"
        - Professional and converting copy!
        """)
    
    st.markdown("### 💡 Try These Commands:")
    
    example_commands = [
        "Create a viral post about the benefits of online learning with an image",
        "Write a welcome email for new Vonza users", 
        "Generate a LinkedIn post about entrepreneurship with a professional image",
        "Create an Instagram post about productivity tips with a vibrant image",
        "Write a sales email for my online course"
    ]
    
    for cmd in example_commands:
        if st.button(f"💬 {cmd}", key=f"example_{hash(cmd)}", use_container_width=True):
            st.session_state['example_prompt'] = cmd
            st.rerun()

def main():
    """Main application function"""
    initialize_session_state()
    
    db = st.session_state.db
    
    # Sidebar for chat management and configuration
    with st.sidebar:
        st.markdown('<div class="sidebar-info">', unsafe_allow_html=True)
        st.header("🤖 genie Assistant")
        st.markdown("Your intelligent executive assistant with **viral content creation** and **DALL-E 3 image generation** (1024×1024)!")
        st.markdown('</div>', unsafe_allow_html=True)
        
        # API Key input
        api_key = st.text_input(
            "OpenAI API Key",
            type="password",
            placeholder="sk-...",
            help="Your OpenAI API key for genie with DALL-E 3 access"
        )
        
        if api_key and not st.session_state.assistant:
            with st.spinner("Initializing genie with DALL-E 3 powers..."):
                assistant = ZuuriAssistant(api_key)
                st.session_state.assistant = assistant
                
                # Get or create the single assistant for this user
                assistant_id = assistant.get_or_create_assistant(
                    st.session_state.user_id, db
                )
                
                if assistant_id:
                    st.session_state.assistant_id = assistant_id
                    st.success("✅ genie is ready with DALL-E 3 Standard (1024×1024)!")
                else:
                    st.error("Failed to initialize genie. Please check your API key.")
        
        # Restore last chat after assistant is initialized
        if st.session_state.assistant and st.session_state.assistant_id:
            restore_last_chat(db, st.session_state.assistant, st.session_state.user_id)
        
        # Chat management
        st.markdown("---")
        st.subheader("💬 Your Chats")
        
        # New chat button
        if st.button("➕ New Chat", use_container_width=True):
            chat_id = create_new_chat(db, st.session_state.user_id)
            st.session_state.current_chat_id = chat_id
            st.session_state.messages = []
            st.rerun()
        
        # List existing chats
        user_chats = db.get_user_chats(st.session_state.user_id)
        
        for chat in user_chats:
            is_active = chat['id'] == st.session_state.current_chat_id
            
            col1, col2 = st.columns([4, 1])
            
            with col1:
                if st.button(
                    chat['title'], 
                    key=f"chat_{chat['id']}",
                    use_container_width=True,
                    type="primary" if is_active else "secondary"
                ):
                    if st.session_state.assistant:
                        load_chat(db, st.session_state.assistant, chat['id'])
                        st.rerun()
            
            with col2:
                if st.button("🗑️", key=f"delete_{chat['id']}", help="Delete chat"):
                    db.delete_chat(chat['id'])
                    if chat['id'] == st.session_state.current_chat_id:
                        st.session_state.current_chat_id = None
                        st.session_state.messages = []
                    st.rerun()
        
        if not user_chats:
            st.info("No chats yet. Create your first viral post!")
        
        # Session info with persistent user
        st.markdown("---")
        st.markdown('<div class="sidebar-info">', unsafe_allow_html=True)
        st.subheader("📊 Session Info")
        st.write(f"**User ID:** `{st.session_state.user_id}`")
        st.write(f"**Total Chats:** {len(user_chats)}")
        st.write("**Image Size:** Standard (1024×1024)")
        
        if st.session_state.assistant_id:
            st.write(f"**Assistant ID:** `{st.session_state.assistant_id[:8]}...`")
        
        if st.session_state.current_chat_id:
            st.write(f"**Current Chat:** `{st.session_state.current_chat_id}`")
            st.write(f"**Messages:** {len(st.session_state.messages)}")
        
        # Show persistence status
        if len(user_chats) > 0:
            st.success("✅ Your chats are saved!")
        else:
            st.info("💡 Start chatting to create your first saved conversation")
        
        st.markdown('</div>', unsafe_allow_html=True)
        
       
    
    # Main chat interface
    if not api_key:
        st.markdown('<div class="chat-header">', unsafe_allow_html=True)
        st.title("🤖 Welcome to genie 2.0")
        st.markdown("### Your Executive Assistant with DALL-E 3 Standard Image Generation")
        st.info("👈 Please enter your OpenAI API key in the sidebar to start creating viral content!")
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Enhanced feature highlights
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("""
            <div class="feature-card">
                <h3>🔥 Viral Content Creator</h3>
                <p>Create engaging posts with DALL-E 3 Standard (1024×1024) images</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown("""
            <div class="feature-card">
                <h3>📧 Email Marketing Pro</h3>
                <p>Write converting emails, sequences, and customer communications</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown("""
            <div class="feature-card">
                <h3>🧠 Perfect Memory</h3>
                <p>Remembers all conversations and builds on previous discussions</p>
            </div>
            """, unsafe_allow_html=True)
        
        # Display content creation examples
        display_content_creation_examples()
        
        return
    
    if not st.session_state.assistant or not st.session_state.assistant_id:
        st.error("Please check your API key and try again.")
        return
    
    # Create first chat if none exists and user is new
    if not st.session_state.current_chat_id:
        user_chats = db.get_user_chats(st.session_state.user_id)
        if not user_chats:  # Only create welcome chat for completely new users
            chat_id = create_new_chat(db, st.session_state.user_id, "Welcome to genie 2.0!")
            st.session_state.current_chat_id = chat_id
    
    # Enhanced welcome message for empty chats
    if not st.session_state.messages:
        st.markdown('<div class="chat-header">', unsafe_allow_html=True)
        st.title("🤖 Hi! I'm genie 2.0")
        st.markdown("### Your Executive Assistant with DALL-E 3 Standard Image Generation")
        st.markdown("I can create **viral social media posts** with **AI-generated images (1024×1024)**, write **converting emails**, and help you with **Vonza business growth**!")
        st.markdown('</div>', unsafe_allow_html=True)
        
    
    # Display chat messages with enhanced formatting
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
            # Display images if any (for future enhancement)
            if 'images' in message and message['images']:
                for image in message['images']:
                    st.image(image, caption="Generated Image (1024×1024)", use_column_width=True)
    
    # Handle quick prompts
    prompt = None
    if 'quick_prompt' in st.session_state:
        prompt = st.session_state['quick_prompt']
        del st.session_state['quick_prompt']
    elif 'example_prompt' in st.session_state:
        prompt = st.session_state['example_prompt']
        del st.session_state['example_prompt']
    else:
        # Enhanced chat input with better placeholder
        prompt = st.chat_input("Ask me to create viral posts with images, write emails, help with Vonza, or anything else...")
    
    if prompt:
        # Get current chat details
        chat_details = db.get_chat_details(st.session_state.current_chat_id)
        
        # Create thread if needed (using the single assistant for this user)
        if not chat_details['thread_id']:
            thread_id = st.session_state.assistant.create_thread()
            if not thread_id:
                st.error("Failed to create conversation thread. Please try again.")
                return
            
            # Update database with thread ID
            db.update_chat(st.session_state.current_chat_id, thread_id=thread_id)
        else:
            thread_id = chat_details['thread_id']
        
        # Add user message to display (temporary, will be refreshed from thread)
        user_message = {"role": "user", "content": prompt}
        st.session_state.messages.append(user_message)
        
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Generate chat title from first message if needed
        if len(st.session_state.messages) == 1:
            new_title = generate_chat_title(prompt)
            db.update_chat(st.session_state.current_chat_id, title=new_title)
        
        # Get assistant response with enhanced capabilities
        with st.chat_message("assistant"):
            with st.spinner("genie is creating amazing content..."):
                response_data = st.session_state.assistant.send_message(
                    thread_id, st.session_state.assistant_id, prompt
                )
                
                response_content = response_data.get("content", "Sorry, I encountered an error.")
                
                # Display the response
                st.markdown(response_content)
                
                # Check if response contains image URLs and display them
                if "![Image]" in response_content or "image_url" in response_content:
                    # Extract image URLs from the response if any
                    import re
                    image_urls = re.findall(r'https://[^\s)]+\.(?:jpg|jpeg|png|gif)', response_content)
                    
                    for img_url in image_urls:
                        try:
                            st.image(img_url, caption="AI Generated Image (1024×1024)", use_column_width=True)
                        except:
                            st.info(f"Generated image: {img_url}")
                
                # Add assistant response to display (temporary)
                assistant_message = {"role": "assistant", "content": response_content}
                st.session_state.messages.append(assistant_message)
                
                # Update the chat's timestamp
                db.update_chat(st.session_state.current_chat_id)
                
                # Show success message for content creation
                if any(keyword in prompt.lower() for keyword in ['viral post', 'create post', 'social media', 'email', 'write email', 'image', 'picture', 'visual']):
                    st.success("🎉 Content created! All images are in Standard 1024×1024 format!")


if __name__ == "__main__":
    main()