import streamlit as st
from greek_sub_publisher import auth

def render_login_page(user_store: auth.UserStore) -> auth.User | None:
    """
    Renders a centered, OpenAI-style login page.
    Returns the authenticated user if login is successful, else None.
    """
    
    # Center the content using columns
    _, col, _ = st.columns([1, 2, 1])
    
    with col:
        st.markdown(
            """
            <div class="login-container">
                <div class="login-logo">🇬🇷</div>
                <div class="login-title">Welcome back</div>
                <div class="login-subtitle">Sign in to Greek Sub Publisher</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        
        # Google Sign In
        google_cfg = auth.google_oauth_config()
        if google_cfg:
            if st.button("Continue with Google", use_container_width=True, type="primary"):
                flow = auth.build_google_flow(google_cfg)
                auth_url, state = flow.authorization_url(
                    access_type="offline",
                    include_granted_scopes="true",
                    prompt="consent",
                )
                st.session_state["google_oauth_state"] = state
                st.session_state["google_auth_url"] = auth_url
            
            if st.session_state.get("google_auth_url") and st.session_state.get("google_oauth_state"):
                st.markdown(
                    f"""
                    <a href="{st.session_state['google_auth_url']}" target="_self" style="text-decoration: none;">
                        <div style="
                            background-color: #27272a; 
                            color: white; 
                            padding: 10px; 
                            border-radius: 6px; 
                            text-align: center; 
                            margin-top: 8px;
                            font-weight: 500;
                            border: 1px solid #3f3f46;
                        ">
                            Authenticate with Google
                        </div>
                    </a>
                    """,
                    unsafe_allow_html=True
                )
        else:
            st.warning("Google login not configured (missing secrets).")

        st.markdown('<div class="login-divider">OR</div>', unsafe_allow_html=True)

        # Email/Password Login
        with st.form("login_form"):
            email = st.text_input("Email address", placeholder="name@example.com")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            submit = st.form_submit_button("Continue", use_container_width=True, type="secondary")
            
            if submit:
                if not email or not password:
                    st.error("Please enter both email and password.")
                else:
                    user = user_store.authenticate_local(email, password)
                    if user:
                        return user
                    else:
                        st.error("Invalid credentials.")
        
        # Registration Link (Toggle)
        if "show_register" not in st.session_state:
            st.session_state["show_register"] = False
            
        if st.button("Don't have an account? Sign up", type="secondary", use_container_width=True):
             st.session_state["show_register"] = not st.session_state["show_register"]
             
        if st.session_state["show_register"]:
            with st.form("register_form"):
                st.markdown("### Create Account")
                new_name = st.text_input("Full Name")
                new_email = st.text_input("Email")
                new_pass = st.text_input("Password", type="password")
                reg_submit = st.form_submit_button("Sign Up", type="primary", use_container_width=True)
                
                if reg_submit:
                    try:
                        user = user_store.register_local_user(new_email, new_pass, new_name)
                        return user
                    except Exception as e:
                        st.error(f"Registration failed: {e}")

    return None
