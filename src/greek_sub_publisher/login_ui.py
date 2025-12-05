import streamlit as st
from greek_sub_publisher import auth


def render_login_page(user_store: auth.UserStore) -> auth.User | None:
    """
    Renders a centered, OpenAI-style login page.
    Returns the authenticated user if login is successful, else None.
    """

    # --- Page Wrapper (Centered) ---
    st.markdown('<div class="login-page-wrapper">', unsafe_allow_html=True)
    
    # Use columns to center the card
    _, col, _ = st.columns([1, 1.5, 1])

    with col:
        # --- Login Card ---
        st.markdown('<div class="login-card">', unsafe_allow_html=True)
        
        # Logo and Title
        st.markdown(
            """
            <div class="login-logo">🇬🇷</div>
            <div class="login-title">Welcome back</div>
            <div class="login-subtitle">Sign in to continue</div>
            """,
            unsafe_allow_html=True,
        )

        # --- Google Sign In ---
        google_cfg = auth.google_oauth_config()
        if google_cfg:
            if not st.session_state.get("google_auth_url") or not st.session_state.get(
                "google_oauth_state"
            ):
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
                    <a href="{google_auth_url}" target="_self" class="google-signin-btn">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
                            <path fill="#EA4335" d="M24 9.5c3.54 0 6 1.54 7.38 2.84l5.4-5.26C33.46 3.42 29.14 1.5 24 1.5 14.96 1.5 7.25 6.74 3.8 14.1l6.48 5.02C11.76 12.8 17.38 9.5 24 9.5z"/>
                            <path fill="#34A853" d="M46.5 24.5c0-1.56-.14-2.7-.44-3.88H24v7.06h12.7c-.26 1.78-1.67 4.46-4.79 6.26l7.35 5.69c4.45-4.1 7.24-10.14 7.24-15.13z"/>
                            <path fill="#FBBC05" d="M10.28 28.88A14.54 14.54 0 0 1 9 24c0-1.7.31-3.34.83-4.88l-6.48-5.02A23.89 23.89 0 0 0 .5 24a23.8 23.8 0 0 0 2.85 11.9l6.93-7.02z"/>
                            <path fill="#4285F4" d="M24 46.5c6.14 0 11.3-2.02 15.07-5.4l-7.35-5.68c-1.97 1.32-4.62 2.24-7.72 2.24-6.63 0-12.24-3.3-14.89-8.12l-6.93 7.02C7.25 41.26 14.96 46.5 24 46.5z"/>
                        </svg>
                        Continue with Google
                    </a>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("Google sign-in is not configured.")

        # --- Divider ---
        st.markdown('<div class="login-divider">or</div>', unsafe_allow_html=True)

        # --- Email/Password Login ---
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("Email", placeholder="name@example.com", label_visibility="collapsed")
            password = st.text_input("Password", type="password", placeholder="Password", label_visibility="collapsed")
            submit = st.form_submit_button("Continue", use_container_width=True, type="primary")

            if submit:
                if not email or not password:
                    st.error("Please enter both email and password.")
                else:
                    user = user_store.authenticate_local(email, password)
                    if user:
                        return user
                    else:
                        st.error("Invalid email or password.")

        # --- Registration Toggle ---
        if "show_register" not in st.session_state:
            st.session_state["show_register"] = False

        st.markdown("<div style='height: 12px'></div>", unsafe_allow_html=True)  # Spacer
        
        if st.button(
            "Create an account" if not st.session_state["show_register"] else "Back to login",
            type="secondary",
            use_container_width=True,
        ):
            st.session_state["show_register"] = not st.session_state["show_register"]
            st.rerun()

        if st.session_state["show_register"]:
            st.markdown("<div style='height: 16px'></div>", unsafe_allow_html=True)
            with st.form("register_form", clear_on_submit=False):
                st.markdown("#### Create your account")
                new_name = st.text_input("Full Name", placeholder="Your Name")
                new_email = st.text_input("Email", placeholder="name@example.com", key="reg_email")
                new_pass = st.text_input("Password", type="password", placeholder="Create a password", key="reg_pass")
                reg_submit = st.form_submit_button("Sign Up", type="primary", use_container_width=True)

                if reg_submit:
                    if not new_name or not new_email or not new_pass:
                        st.error("Please fill in all fields.")
                    else:
                        try:
                            user = user_store.register_local_user(new_email, new_pass, new_name)
                            return user
                        except Exception as e:
                            st.error(f"Registration failed: {e}")

        st.markdown("</div>", unsafe_allow_html=True)  # Close login-card
    
    st.markdown("</div>", unsafe_allow_html=True)  # Close login-page-wrapper
    return None


def render_profile_page(user: auth.User, user_store: auth.UserStore) -> None:
    """Render the user profile settings page."""
    st.markdown("## Profile")

    # --- Profile Header ---
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(
            f"""
            <div style="background: linear-gradient(135deg, #10a37f 0%, #1a7f64 100%); border-radius: 50%; width: 72px; height: 72px; display: flex; align-items: center; justify-content: center; font-size: 28px; font-weight: 700; color: #fff;">
                {user.name[0].upper() if user.name else "U"}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(f"### {user.name}")
        st.caption(f"{user.email}")
        st.caption(f"Signed in with {user.provider.capitalize()}")

    st.markdown("---")

    # --- Account Settings (Local Users Only) ---
    if user.provider == "local":
        st.markdown("#### Account Settings")

        with st.form("update_profile"):
            new_name = st.text_input("Display Name", value=user.name)

            st.markdown("##### Change Password")
            st.caption("Leave blank to keep your current password.")
            new_pass = st.text_input("New Password", type="password")
            confirm_pass = st.text_input("Confirm New Password", type="password")

            if st.form_submit_button("Save Changes", type="primary"):
                if new_name and new_name != user.name:
                    user_store.update_name(user.id, new_name)
                    st.session_state["user"]["name"] = new_name
                    st.success("Name updated!")
                    st.rerun()

                if new_pass:
                    if new_pass != confirm_pass:
                        st.error("Passwords do not match.")
                    else:
                        user_store.update_password(user.id, new_pass)
                        st.success("Password updated!")

    else:
        st.info(f"Your account is managed by {user.provider.capitalize()}.")

    st.markdown("---")

    # --- Connected Apps ---
    st.markdown("#### Connected Apps")

    tt_tokens = st.session_state.get("tiktok_tokens")
    if tt_tokens:
        st.success("✓ TikTok is connected")
        if st.button("Disconnect TikTok", type="secondary"):
            st.session_state.pop("tiktok_tokens", None)
            st.rerun()
    else:
        st.caption("No apps connected yet.")
