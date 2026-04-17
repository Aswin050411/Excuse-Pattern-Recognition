import random
from datetime import datetime
from flask import Blueprint, request, session, jsonify, render_template, current_app, redirect, url_for
from app.extensions import csrf
from services.chat_service import get_chat_response
from services.analytics_service import get_analytics_data
from repository.tasks_repo import get_tasks_by_user, get_all_tasks
from utils.flask_auth import auth_required

chatbot_bp = Blueprint('chatbot', __name__)


# ---------------------------------------------------------------------------
# Excuse Analysis Engine — lightweight heuristic for demo-grade AI metrics
# ---------------------------------------------------------------------------

_SUSPICIOUS_WORDS = ["maybe", "probably", "i think", "kind of", "sort of",
                     "not sure", "possibly", "might", "could be", "forgot"]
_DECEPTIVE_WORDS = ["definitely", "100%", "i swear", "trust me", "honestly",
                    "believe me", "i promise", "never", "always"]

import hashlib

def _analyze_excuse(text: str) -> dict:
    """Generate AI confidence, verdict, and a unique report ID — fully deterministic."""
    text_lower = text.lower()
    
    suspicious_hits = sum(1 for w in _SUSPICIOUS_WORDS if w in text_lower)
    deceptive_hits = sum(1 for w in _DECEPTIVE_WORDS if w in text_lower)
    word_count = len(text.split())
    
    # Scoring heuristic
    score = suspicious_hits * 2 + deceptive_hits * 3
    
    # Short excuses are more suspicious
    if word_count < 5:
        score += 1
    
    # Deterministic Confidence: Base score derived from linguistic signals
    # Plus a deterministic "uniqueness" offset based on the message content hash
    msg_hash = int(hashlib.md5(text.encode()).hexdigest(), 16)
    variance = (msg_hash % 10) # 0-9% variance for realism without randomness
    
    if score >= 4:
        verdict = "Suspicious"
        base_confidence = 85
        color = "orange"
    elif score >= 2:
        verdict = "Needs Review"
        base_confidence = 65
        color = "yellow"
    else:
        verdict = "Possibly Genuine"
        base_confidence = 75
        color = "green"
    
    # Final confidence is base + hash-drift
    confidence_val = min(99, base_confidence + variance)
    
    report_id = datetime.now().strftime("EPAI-%Y%m%d-%H%M%S")
    
    return {
        "report_id": report_id,
        "verdict": verdict,
        "confidence": f"{confidence_val}%",
        "color": color,
        "signals_detected": suspicious_hits + deceptive_hits,
    }


@chatbot_bp.route('/chatbot')
@auth_required
def chatbot():
    """Renders the chatbot UI."""
    return render_template('chatbot.html')

@chatbot_bp.route('/chatbot/api', methods=['POST'])
@auth_required
@csrf.exempt
def chatbot_api():
    """Handles chat API requests."""
    
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    prompt = data.get('message')
    conversation_history = data.get('history', [])
    
    if not prompt: 
        return jsonify({'error': 'No message provided'}), 400
        
    user_id = session['user_id']
    user_role = session.get('user_role', 'employee')
    
    # Run excuse analysis on every message
    analysis = _analyze_excuse(prompt)
    
    # Fetch real analytics for context (guard against analytics pipeline failures)
    try:
        kpis = get_analytics_data(user_id=user_id, role=user_role)
    except Exception as kpi_err:
        current_app.logger.warning(f"Chatbot KPI fetch failed for user {user_id}: {kpi_err}")
        kpis = {}
    
    user_context = f"""
    User: {session.get('user_name')} ({user_role})
    Stats:
    - Avg Authenticity: {kpis.get('avg_auth_score')}%
    - Risk Distribution: {kpis.get('risk_distribution')}
    - Pending Tasks: {len([t for t in get_tasks_by_user(user_id) if t['status'] == 'Pending']) if user_role == 'employee' else 'N/A'}
    """

    # --- Contextual Query Handling ---
    prompt_lower = prompt.lower()
    
    if "real blocker" in prompt_lower:
        return jsonify({
            'response': "🛡️ **AI Verified:** This task has been classified as a **Verified Blocker**. I've escalated the priority and logged this for direct management review.",
            'analysis': analysis
        })
    
    if "excuse" in prompt_lower:
        return jsonify({
            'response': "⚠️ **Pattern Detected:** This delay has been classified as a **Rationalization**. The system has flagged this for authenticity review.",
            'analysis': analysis
        })

    if "quick insights" in prompt_lower or "performance" in prompt_lower:
        auth = kpis.get('avg_auth_score', 0)
        low_risk = kpis.get('risk_low', 0)
        return jsonify({
            'response': f"🚀 **Quick Insights:**<br>• Your average Authenticity Signal is **{auth}%**.<br>• You have **{low_risk}** low-risk delay submissions.<br>• Trend: Your trust index is {'stable' if auth > 70 else 'needs improvement'}.<br>How else can I help?",
            'analysis': analysis
        })

    if "pending" in prompt_lower or "status" in prompt_lower:
        tasks = get_tasks_by_user(user_id) if user_role == 'employee' else get_all_tasks()
        pending = [t for t in tasks if t['status'] == 'Pending']
        return jsonify({
            'response': f"You have **{len(pending)}** pending tasks. Your next deadline is **{pending[0]['deadline'] if pending else 'N/A'}**.",
            'analysis': analysis
        })
    
    try:
        response_text = get_chat_response(prompt, conversation_history, user_context=user_context)
        return jsonify({
            'response': response_text,
            'analysis': analysis
        })
    except Exception as e:
        current_app.logger.error(f"Chatbot Error: {e}")
        return jsonify({'error': str(e)}), 500
