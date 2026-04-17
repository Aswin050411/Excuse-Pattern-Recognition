from .db import execute_query, get_db_cursor
import re
import logging

logger = logging.getLogger(__name__)

def count_admins():
    """Count total number of admins in the system."""
    try:
        # PostgreSQL returns count as integer
        result = execute_query("SELECT COUNT(*) as count FROM users WHERE role='admin'", fetch=True)
        return result[0]['count'] if result else 0
    except Exception as e:
        logger.error("Error counting admins: %s", e)
        return 0

# get_or_create_org REMOVED (Organization feature disabled/simplified)

def create_user(full_name, email, password_hash, role='employee', job_role=None, avatar_url=None, bio=None, phone=None, city=None, country=None, postal_code=None):
    """Create a new user with validation."""
    # Input validation
    if not full_name or not full_name.strip():
        raise ValueError("Full name cannot be empty")
    if not email or not email.strip():
        raise ValueError("Email cannot be empty")
    
    # Email format validation
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_regex, email):
        raise ValueError("Invalid email format")
    
    # Role validation
    valid_roles = ['employee', 'manager', 'admin']
    if role not in valid_roles:
        raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")
    
    try:
        # Use RETURNING id to get the new ID immediately
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (full_name, email, password_hash, role, job_role, avatar_url, bio, phone, city, country, postal_code) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                RETURNING id
                """,
                (
                    full_name.strip(), 
                    email.strip().lower(), 
                    password_hash, 
                    role, 
                    job_role,
                    avatar_url,
                    bio,
                    phone,
                    city,
                    country,
                    postal_code
                )
            )
            new_user = cursor.fetchone()
            # conn.commit() is handled by context manager on exit
            if new_user:
                return new_user['id']
            raise Exception("Failed to retrieve new user ID")
            
    except Exception as e:
        if 'unique constraint' in str(e).lower():
            raise ValueError(f"User with email {email} already exists")
        raise Exception(f"Failed to create user: {str(e)}")

def get_user_by_email(email):
    """Get user by email address."""
    if not email:
        return None
    
    try:
        users = execute_query("SELECT * FROM users WHERE email = %s", (email.strip().lower(),))
        return users[0] if users else None
    except Exception as e:
        logger.error("Error fetching user by email: %s", e)
        return None

def get_user_by_id(user_id):
    try:
        users = execute_query("SELECT * FROM users WHERE id = %s", (user_id,))
        return users[0] if users else None
    except Exception:
        return None

def get_all_users(active_only=False):
    sql = "SELECT id, full_name, email, role, active_status, created_at FROM users"
    if active_only:
        sql += " WHERE active_status = TRUE"
    return execute_query(sql)

def update_user(user_id, full_name, email, role, active_status):
    """Update user information with validation."""
    if not user_id:
        raise ValueError("User ID is required")
    if not full_name or not full_name.strip():
        raise ValueError("Full name cannot be empty")
    
    valid_roles = ['employee', 'manager', 'admin']
    if role not in valid_roles:
        raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")
    
    # execute_query returns rowcount if fetch=False? 
    # connection.py says: if fetch: return fetchall(), else return rowcount
    row_count = execute_query(
        "UPDATE users SET full_name=%s, email=%s, role=%s, active_status=%s WHERE id=%s",
        (full_name.strip(), email.strip().lower(), role, active_status, user_id),
        fetch=False
    )
    
    if row_count == 0:
        raise ValueError(f"User with ID {user_id} not found")

def soft_delete_user(user_id):
    """Soft delete a user by setting active_status to FALSE."""
    if not user_id:
        raise ValueError("User ID is required")
        
    try:
        execute_query(
            "UPDATE users SET active_status=FALSE WHERE id=%s",
            (user_id,),
            fetch=False
        )
        logger.info("User %s soft deleted.", user_id)
        return True
    except Exception as e:
        logger.error("Error soft deleting user %s: %s", user_id, e)
        raise

def update_password_hash(user_id, new_hash):
    """Update only the password hash for a user."""
    execute_query(
        "UPDATE users SET password_hash=%s WHERE id=%s",
        (new_hash, user_id),
        fetch=False
    )

def update_user_reliability(user_id, score):
    """Update a user's reliability score."""
    execute_query(
        "UPDATE users SET reliability_score=%s WHERE id=%s",
        (score, user_id),
        fetch=False
    )

def get_avg_reliability():
    """Get average reliability score across all active users."""
    res = execute_query("SELECT AVG(reliability_score) as avg FROM users WHERE active_status = TRUE")
    return res[0]['avg'] if res and res[0]['avg'] else 100.0

def update_user_profile(user_id, **kwargs):
    """Update user profile information (self-service)."""
    if not user_id:
        raise ValueError("User ID is required")
    
    fields = []
    values = []
    
    for key in ['full_name', 'email', 'avatar_url', 'bio', 'phone', 'city', 'country', 'postal_code']:
        if key in kwargs:
            val = kwargs[key]
            if key == 'full_name' and (not val or not val.strip()):
                continue
            if key == 'email' and (not val or not val.strip()):
                continue
            
            fields.append(f"{key}=%s")
            values.append(val.strip() if isinstance(val, str) else val)

    if not fields:
        return

    values.append(user_id)
    sql = f"UPDATE users SET {', '.join(fields)} WHERE id=%s"
    execute_query(sql, tuple(values), fetch=False)

def update_last_active(user_id):
    """Update the last_active_at timestamp for a user. robustly handles missing columns."""
    try:
        execute_query(
            "UPDATE users SET last_active_at = NOW() WHERE id = %s",
            (user_id,),
            fetch=False
        )
    except Exception as e:
        # Log once to avoid spamming logs if the column really is missing
        logger.debug("Could not update last_active_at (likely missing column): %s", e)

def get_active_users_count(minutes=5):
    """Get count of users active in the last X minutes."""
    try:
        # Use make_interval to safely parameterize the minutes value
        # (INTERVAL '%s minutes' is NOT parameterized by psycopg2 — SQL injection risk)
        res = execute_query(
            "SELECT COUNT(*) as count FROM users WHERE last_active_at >= NOW() - make_interval(mins => %s)",
            (int(minutes),),
            fetch=True
        )
        return res[0]['count'] if res else 0
    except Exception as e:
        logger.error("Error counting active users: %s", e)
        return 0

def get_active_user_list(minutes=15):
    """Get list of users active in the last X minutes."""
    try:
        # Use make_interval to safely parameterize the minutes value
        return execute_query(
            "SELECT id, full_name, email, role, last_active_at FROM users WHERE last_active_at >= NOW() - make_interval(mins => %s) ORDER BY last_active_at DESC",
            (int(minutes),),
            fetch=True
        )
    except Exception as e:
        logger.error("Error fetching active users: %s", e)
        return []
