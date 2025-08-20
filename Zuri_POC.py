import streamlit as st
import sqlite3
from openai import OpenAI
from datetime import datetime
import json
import uuid
import time
import os
from typing import Optional, Dict, List

# Page configuration
st.set_page_config(
    page_title="Zurii - Executive Assistant",
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
</style>
""", unsafe_allow_html=True)

class DatabaseManager:
    """Handles all database operations"""
    
    def __init__(self, db_path="zurii_chats.db"):
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
    """Handles OpenAI Assistant operations"""
    
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o-mini"
    
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
        
        # Create new assistant
        try:
            assistant = self.client.beta.assistants.create(
                name="Zurii - Executive Assistant",
                instructions="""You are Zurii, a friendly and knowledgeable executive assistant for Vonza.

Your main responsibilities:
• Answer questions about Vonza platform and features with detailed, accurate information
• Provide quick, practical help and creative solutions for business challenges
• Offer general assistance and support for productivity and business tasks
• Act as a 24/7 creative assistant for brainstorming and problem-solving
• Help with task planning, organization, and workflow optimization

Key behaviors:
• Always be helpful, concise, and accurate in your responses
• When you don't know something specific about Vonza, be honest and provide general guidance
• Ask clarifying questions when user requests are unclear or could benefit from more context
• Provide actionable advice and step-by-step solutions
• Be proactive in suggesting helpful ideas and improvements
• Maintain a friendly, professional tone that builds confidence
• Remember context from our conversation to provide personalized assistance
• Focus on practical solutions that save time and improve efficiency

Areas of expertise:
• Vonza platform features and best practices
• Online course creation and marketing
• Business automation and workflows
• Customer service and communication
• Content creation and strategy
• Project management and organization

Remember: You're here to make the user's work easier and more successful. Always aim to solve problems completely and anticipate follow-up needs.""",
                model=self.model,
                tools=[{"type": "code_interpreter"}]
            )
            
            # Save assistant_id for this user
            db.update_user_assistant(user_id, assistant.id)
            return assistant.id
            
        except Exception as e:
            st.error(f"Error creating assistant: {str(e)}")
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
                if msg.content:
                    for content_item in msg.content:
                        if hasattr(content_item, 'text'):
                            content += content_item.text.value
                
                formatted_messages.append({
                    'role': msg.role,
                    'content': content,
                    'created_at': msg.created_at
                })
            
            return formatted_messages
            
        except Exception as e:
            st.error(f"Error retrieving messages: {str(e)}")
            return []
    
    def send_message(self, thread_id: str, assistant_id: str, message: str) -> str:
        """Send message and get response from assistant"""
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
            
            # Wait for completion with timeout
            max_wait = 30  # 30 seconds timeout
            wait_time = 0
            
            while run.status in ['queued', 'in_progress'] and wait_time < max_wait:
                time.sleep(1)
                wait_time += 1
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
            
            if run.status == 'completed':
                # Get the latest messages
                messages = self.client.beta.threads.messages.list(
                    thread_id=thread_id,
                    limit=1
                )
                
                if messages.data:
                    return messages.data[0].content[0].text.value
                else:
                    return "I apologize, but I didn't receive a proper response. Could you try asking again?"
            
            elif run.status == 'failed':
                return f"I encountered an error processing your request. Please try again."
            
            else:
                return f"Request timed out. Please try again with a shorter message."
                
        except Exception as e:
            return f"I apologize, but I encountered an error: {str(e)}. Please try again."

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

def main():
    """Main application function"""
    initialize_session_state()
    
    db = st.session_state.db
    
    # Sidebar for chat management and configuration
    with st.sidebar:
        st.markdown('<div class="sidebar-info">', unsafe_allow_html=True)
        st.header("🤖 Zurii Assistant")
        st.markdown("Your intelligent executive assistant with memory")
        st.markdown('</div>', unsafe_allow_html=True)
        
        # API Key input
        api_key = st.text_input(
            "OpenAI API Key",
            type="password",
            placeholder="sk-...",
            help="Your OpenAI API key for Zurii"
        )
        
        if api_key and not st.session_state.assistant:
            with st.spinner("Initializing Zurii..."):
                assistant = ZuuriAssistant(api_key)
                st.session_state.assistant = assistant
                
                # Get or create the single assistant for this user
                assistant_id = assistant.get_or_create_assistant(
                    st.session_state.user_id, db
                )
                
                if assistant_id:
                    st.session_state.assistant_id = assistant_id
                    st.success("✅ Zurii is ready!")
                else:
                    st.error("Failed to initialize Zurii. Please check your API key.")
        
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
            st.info("No chats yet. Create your first chat!")
        
        # Session info with persistent user
        st.markdown("---")
        st.markdown('<div class="sidebar-info">', unsafe_allow_html=True)
        st.subheader("📊 Session Info")
        st.write(f"**User ID:** `{st.session_state.user_id}`")
        st.write(f"**Total Chats:** {len(user_chats)}")
        
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
        
        # About Zurii
        st.markdown("---")
        st.markdown('<div class="sidebar-info">', unsafe_allow_html=True)
        st.subheader("💡 What I can help with:")
        st.markdown("""
        • **Vonza platform expertise**
        • **Business strategy & planning**
        • **Creative problem solving** 
        • **Task automation ideas**
        • **Content & marketing help**
        • **Process optimization**
        • **And much more!**
        """)
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Main chat interface
    if not api_key:
        st.markdown('<div class="chat-header">', unsafe_allow_html=True)
        st.title("🤖 Welcome to Zurii")
        st.markdown("### Your Executive Assistant with Perfect Memory")
        st.info("👈 Please enter your OpenAI API key in the sidebar to start chatting")
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Feature highlights
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("""
            **🧠 Perfect Memory**
            - Remembers all conversations
            - Context across chats
            - Builds on previous discussions
            """)
        
        with col2:
            st.markdown("""
            **💬 Multiple Chats**
            - Organize by topic
            - Switch between projects
            - Never lose context
            """)
        
        with col3:
            st.markdown("""
            **🎯 Specialized for Vonza**
            - Platform expertise
            - Business assistance
            - Creative solutions
            """)
        
        return
    
    if not st.session_state.assistant or not st.session_state.assistant_id:
        st.error("Please check your API key and try again.")
        return
    
    # Create first chat if none exists and user is new
    if not st.session_state.current_chat_id:
        user_chats = db.get_user_chats(st.session_state.user_id)
        if not user_chats:  # Only create welcome chat for completely new users
            chat_id = create_new_chat(db, st.session_state.user_id, "Welcome to Zurii!")
            st.session_state.current_chat_id = chat_id
    
    # Welcome message for empty chats
    if not st.session_state.messages:
        st.markdown('<div class="chat-header">', unsafe_allow_html=True)
        st.title("🤖 Hi! I'm Zurii")
        st.markdown("### Your Executive Assistant with Perfect Memory")
        st.markdown("I remember our entire conversation history and can help you with Vonza, business tasks, and creative problem-solving!")
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask Zurii anything about Vonza or get business help..."):
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
        
        # Get assistant response
        with st.chat_message("assistant"):
            with st.spinner("Zurii is thinking..."):
                response = st.session_state.assistant.send_message(
                    thread_id, st.session_state.assistant_id, prompt
                )
                st.markdown(response)
                
                # Add assistant response to display (temporary)
                assistant_message = {"role": "assistant", "content": response}
                st.session_state.messages.append(assistant_message)
                
                # Update the chat's timestamp
                db.update_chat(st.session_state.current_chat_id)
                
                # Note: Messages are now stored in OpenAI's thread, not in our database
                # To retrieve them later, we use get_thread_messages()


if __name__ == "__main__":
    main()