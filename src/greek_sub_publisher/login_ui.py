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
            # Prebuild the auth URL and state once per session so the button is a single click.
            if not st.session_state.get("google_auth_url") or not st.session_state.get("google_oauth_state"):
                flow = auth.build_google_flow(google_cfg)
                auth_url, state = flow.authorization_url(
                    access_type="offline",
                    include_granted_scopes="true",
                    prompt="consent",
                )
                st.session_state["google_oauth_state"] = state
                st.session_state["google_auth_url"] = auth_url

            google_auth_url = st.session_state.get("google_auth_url")
            if google_auth_url:
                st.markdown(
                    f"""
                    <a href="{google_auth_url}" target="_self" style="text-decoration: none;">
                        <div style="
                            display: inline-flex;
                            align-items: center;
                            gap: 10px;
                            padding: 14px 18px;
                            width: 100%;
                            justify-content: center;
                            border-radius: 12px;
                            background: linear-gradient(135deg, #4285F4 0%, #34A853 50%, #FBBC05 75%, #EA4335 100%);
                            color: #0b0c10;
                            font-weight: 700;
                            letter-spacing: 0.01em;
                            box-shadow: 0 8px 24px rgba(0,0,0,0.25);
                        ">
                            <span style="background: #fff; border-radius: 50%; padding: 6px; display: inline-flex;">
                                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="22" height="22">
                                    <path fill="#EA4335" d="M24 9.5c3.54 0 6 1.54 7.38 2.84l5.4-5.26C33.46 3.42 29.14 1.5 24 1.5 14.96 1.5 7.25 6.74 3.8 14.1l6.48 5.02C11.76 12.8 17.38 9.5 24 9.5z"/>
                                    <path fill="#34A853" d="M46.5 24.5c0-1.56-.14-2.7-.44-3.88H24v7.06h12.7c-.26 1.78-1.67 4.46-4.79 6.26l7.35 5.69c4.45-4.1 7.24-10.14 7.24-15.13z"/>
                                    <path fill="#FBBC05" d="M10.28 28.88A14.54 14.54 0 0 1 9 24c0-1.7.31-3.34.83-4.88l-6.48-5.02A23.89 23.89 0 0 0 .5 24a23.8 23.8 0 0 0 2.85 11.9l6.93-7.02z"/>
                                    <path fill="#4285F4" d="M24 46.5c6.14 0 11.3-2.02 15.07-5.4l-7.35-5.68c-1.97 1.32-4.62 2.24-7.72 2.24-6.63 0-12.24-3.3-14.89-8.12l-6.93 7.02C7.25 41.26 14.96 46.5 24 46.5z"/>
                                </svg>
                            </span>
                            <span style="color:#fff;">Continue with Google</span>
                        </div>
                    </a>
                    """,
                    unsafe_allow_html=True,
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
