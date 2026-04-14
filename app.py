from flask import Flask, request, jsonify, render_template, send_from_directory, redirect, url_for
import joblib
from dataclasses import dataclass
import pandas as pd
from flask_mail import Mail, Message
from flask_cors import CORS
import json
import time
import os
from datetime import datetime
from collections import deque

latest_data_store = {}

# ----------------------
# Setup Flask
# ----------------------
app = Flask(__name__, 
            template_folder='templates',  # Tell Flask where HTML files are
            static_folder='static')        # Tell Flask where static files are
CORS(app)

# Email config - REPLACE with your app password
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587  # Changed to 587 (better deliverability)
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'breaker.monitor.system@gmail.com'
app.config['MAIL_PASSWORD'] = 'kzng lhzr elww gyyu'  # CHANGE THIS
app.config['MAIL_DEFAULT_SENDER'] = 'breaker.monitor.system@gmail.com'

try:
    mail = Mail(app)
    print("✓ Email service initialized with TLS on port 587")
except Exception as e:
    print(f"✗ Email initialization error: {e}")
    mail = None
# ----------------------
# Load Models
# ----------------------
try:
    if os.path.exists("ml/hotspot_model.pkl"):
        hotspot_model = joblib.load("ml/hotspot_model.pkl")
        print("✓ Hotspot model loaded")
    else:
        print("✗ Hotspot model file not found")
        
    if os.path.exists("ml/overload_model.pkl"):
        overload_model = joblib.load("ml/overload_model.pkl")
        print("✓ Overload model loaded")
    else:
        print("✗ Overload model file not found")

except Exception as e:
    print(f"Error loading models: {e}")


# ----------------------
# STREAMING SLOPE (MUST BE HERE)
# ----------------------
N = 10
time_step = 1

temp_buffer = deque(maxlen=N)
current_buffer = deque(maxlen=N)


def compute_slope(temp, current):
    temp_buffer.append(temp)
    current_buffer.append(current)

    if len(temp_buffer) < 2:
        return 0.0, 0.0

    dt = (len(temp_buffer) - 1) * time_step

    if dt == 0:
        return 0.0, 0.0

    thermal_slope = (temp_buffer[-1] - temp_buffer[0]) / dt * 5
    current_slope = (current_buffer[-1] - current_buffer[0]) / dt * 5

    return thermal_slope, current_slope

# ----------------------
# Sensor Reading Dataclass
# ----------------------
@dataclass
class SensorReading:
    ambient_temp_c: float
    temperature_c: float
    temperature_rise_c: float
    current_a: float
    thermal_slope_c_per_5s: float
    current_slope_a_per_5s: float

# ----------------------
# Prediction Function
# ----------------------
def predict_risk(reading: SensorReading) -> dict:
    global hotspot_model, overload_model

    # 🔴 ADD THIS HERE
    if hotspot_model is None or overload_model is None:
        raise Exception("Models not loaded properly")

    x_new = pd.DataFrame([{
    "ambient_temp_c": reading.ambient_temp_c,
    "temperature_c": reading.temperature_c,
    "temperature_rise_c": reading.temperature_rise_c,
    "current_a": reading.current_a,
    "thermal_slope_c_per_5s": reading.thermal_slope_c_per_5s,
    "current_slope_a_per_5s": reading.current_slope_a_per_5s,
}])

# FORCE ORDER
    x_new = x_new[[
    "ambient_temp_c",
    "temperature_c",
    "temperature_rise_c",
    "current_a",
    "thermal_slope_c_per_5s",
    "current_slope_a_per_5s"
]]

    hotspot_prob = float(hotspot_model.predict_proba(x_new)[0, 1])
    overload_prob = float(overload_model.predict_proba(x_new)[0, 1])

    return {
        "hotspot_prob": hotspot_prob,
        "overload_prob": overload_prob,
        "hotspot_flag": int(hotspot_prob >= 0.75),
        "overload_flag": int(overload_prob >= 0.5),
        "composite_risk": 0.5 * hotspot_prob + 0.5 * overload_prob,
    }

 
# ----------------------
# Email Alert Function with BCC (Hidden Recipients)
# ----------------------
def send_breaker_alert(reading, risk, alert_type):
    if mail is None:
        return False, "Email service not configured"
    
    # Define multiple recipients (all will be hidden from each other)
    bcc_recipients = [
        'mariamonicaragunjanvillaflor@gmail.com',      # Main recipient
       # 'gwenlykapergis@gmail.com',   # Secondary recipient
        #'janelledelasoledad9@gmail.com',
        #'mercymicadespabiladeras@gmail.com',
        # Add more emails here - all will be hidden from each other
    ]
    
    if alert_type == "overheating":
        subject = "🔥 CRITICAL: Breaker Overheating Alert!"
        body = f"""
⚠️ IMMEDIATE ACTION REQUIRED ⚠️

BREAKER OVERHEATING DETECTED!

Current Readings:
• Temperature: {reading.temperature_c:.1f}°C
• Current: {reading.current_a:.1f}A
• Temperature Rise: {reading.temperature_rise_c:.1f}°C
• Ambient Temp: {reading.ambient_temp_c:.1f}°C

Risk Assessment:
• Hotspot Probability: {risk['hotspot_prob']*100:.1f}%
• Overload Probability: {risk['overload_prob']*100:.1f}%

Recommended Action:
🚨 IMMEDIATE: Isolate circuit and investigate!

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
This is an automated alert from the Breaker Monitoring System.
        """
    elif alert_type == "prevention":
        subject = "⚠️ PREVENTION: Potential Overload Detected!"
        body = f"""
⚠️ PREVENTIVE ACTION RECOMMENDED ⚠️

POTENTIAL OVERLOAD DEVELOPING!

Current Readings:
• Temperature: {reading.temperature_c:.1f}°C
• Current: {reading.current_a:.1f}A
• Temperature Rise: {reading.temperature_rise_c:.1f}°C
• Ambient Temp: {reading.ambient_temp_c:.1f}°C

Risk Assessment:
• Potential overload condition developing
• Take preventive action now

Recommended Action:
🛡️ PROACTIVE: Reduce load by 15-20% to prevent critical condition!

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
This is an automated alert from the Breaker Monitoring System.
        """
    else:
        subject = "⚠️ Breaker Alert: Combined Risk Detected!"
        body = f"""
⚠️ ALERT: Breaker Risk Detected!

Current Readings:
• Temperature: {reading.temperature_c:.1f}°C
• Current: {reading.current_a:.1f}A
• Temperature Rise: {reading.temperature_rise_c:.1f}°C

Risk Assessment:
• Hotspot Probability: {risk['hotspot_prob']*100:.1f}%
• Overload Probability: {risk['overload_prob']*100:.1f}%

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
This is an automated alert from the Breaker Monitoring System.
        """
    
    try:
        # Create message with BCC only - recipients hidden from each other
        msg = Message(
            subject=subject,
            sender=app.config['MAIL_USERNAME'],
            recipients=[],                      # Empty visible recipients
            bcc=bcc_recipients,                 # All recipients hidden
            reply_to=app.config['MAIL_USERNAME']
        )
        msg.body = body
        
        # Add additional headers to avoid spam
        msg.extra_headers = {
            'X-Priority': '1',
            'X-MSMail-Priority': 'High',
            'Importance': 'High',
            'X-Mailer': 'Breaker Monitoring System v1.0'
        }
        
        mail.send(msg)
        
        # Log who received the email (without revealing to others)
        print(f"✓ Email sent to {len(bcc_recipients)} recipients (BCC hidden): {subject}")
        
        return True, f"Alert sent to {len(bcc_recipients)} recipients (BCC)"
        
    except Exception as e:
        print(f"✗ Email error: {e}")
        return False, f"Failed to send alert: {str(e)}"
    
# ----------------------
# Alert Tracking
# ----------------------
last_alert_time = {}
ALERT_COOLDOWN_SECONDS = 300

def should_send_alert(alert_type):
    current_time = time.time()
    if alert_type in last_alert_time:
        if current_time - last_alert_time[alert_type] < ALERT_COOLDOWN_SECONDS:
            return False
    last_alert_time[alert_type] = current_time
    return True

# ----------------------
# ROUTES - Now using templates folder with redirect fix
# ----------------------

@app.route('/')
def index():
    """Serve the main dashboard"""
    try:
        return render_template('index.html')
    except Exception as e:
        return f"Error loading index.html: {e}", 404

@app.route('/index.html')
def index_html():
    """Handle direct access to index.html by redirecting to root"""
    return redirect(url_for('index'))

@app.route('/full_history.html')
def full_history():
    """Serve the full history page"""
    try:
        return render_template('full_history.html')
    except Exception as e:
        return f"Error loading full_history.html: {e}", 404

# Optional: Catch-all for any other HTML files
@app.route('/<page>.html')
def serve_html_page(page):
    """Serve any HTML file from templates folder"""
    try:
        return render_template(f'{page}.html')
    except Exception:
        return f"Page {page}.html not found", 404

# ----------------------
# API Endpoints
# ----------------------

@app.route("/api/check-alert", methods=['POST'])
def check_alert():
    try:
        data = request.json

        print(f"Received alert check: Temp={data.get('temperature')}°C, Current={data.get('current')}A")

        # ----------------------
        # Extract input values
        # ----------------------
        ambient_temp = float(data.get('ambient_temp_c', 25.0))
        temperature = float(data['temperature'])
        current = float(data['current'])

        thermal_slope, current_slope = compute_slope(temperature, current)

        # ----------------------
        # Build Sensor Reading
        # ----------------------
        reading = SensorReading(
            ambient_temp_c=ambient_temp,
            temperature_c=temperature,
            temperature_rise_c=temperature - ambient_temp,
            current_a=current,
            thermal_slope_c_per_5s=thermal_slope,
            current_slope_a_per_5s=current_slope
        )

        # ----------------------
        # ML Prediction
        # ----------------------
        risk = predict_risk(reading)

        # ----------------------
        # ✅ DETERMINE BREAKER STATE (AFTER risk)
        # ----------------------
        if risk['hotspot_prob'] > 0.8:
            breaker_state = "Overheating"
        elif risk['overload_prob'] > 0.6:
            breaker_state = "Overload"
        else:
            breaker_state = "Normal"

        # ----------------------
        # ✅ UPDATE DASHBOARD DATA (FIXED)
        # ----------------------
        global latest_data_store
        latest_data_store = {
            "temperature": temperature,
            "current": current,
            "breakerState": breaker_state,
            "systemStatus": "Online",
            "date": datetime.now().strftime('%Y-%m-%d'),
            "time": datetime.now().strftime('%H:%M:%S'),
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # ----------------------
        # ALERT LOGIC
        # ----------------------
        alert_sent = False
        alert_messages = []
        alert_type = None

        if risk['hotspot_prob'] > 0.8:
            alert_type = "overheating"
        elif risk['overload_prob'] > 0.6:
            alert_type = "prevention"
        elif temperature > 80:
            alert_type = "overheating"
        elif current > 25:
            alert_type = "prevention"

        if alert_type:
            if should_send_alert(alert_type):
                success, msg = send_breaker_alert(reading, risk, alert_type)

                if success:
                    alert_sent = True
                    alert_messages.append(f"{alert_type.capitalize()} alert sent")
                else:
                    alert_messages.append(f"Failed: {msg}")
            else:
                alert_messages.append(f"{alert_type.capitalize()} alert skipped (cooldown active)")
        else:
            alert_messages.append("No alert triggered")

        return jsonify({
            "success": True,
            "alert_sent": alert_sent,
            "alert_type": alert_type,
            "messages": alert_messages,
            "risk": risk
        })

    except Exception as e:
        print(f"Error in check_alert: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/test-alert")
def test_alert():
    test_reading = SensorReading(
        ambient_temp_c=35.0,
        temperature_c=92.0,
        temperature_rise_c=57.0,
        current_a=38.0,
        thermal_slope_c_per_5s=45.0,
        current_slope_a_per_5s=8.0
    )

    risk = predict_risk(test_reading)

    # ----------------------
    # CONSISTENT LOGIC (same as main API)
    # ----------------------
    if risk['hotspot_prob'] > 0.8:
        alert_type = "overheating"
    elif risk['overload_prob'] > 0.6:
        alert_type = "prevention"
    else:
        return "No alert triggered for test data."

    success, msg = send_breaker_alert(test_reading, risk, alert_type)

    if success:
        return f"Test alert sent successfully!\n\n{msg}"
    else:
        return f"Failed to send test alert: {msg}", 500

@app.route("/api/health", methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "models_loaded": hotspot_model is not None and overload_model is not None,
        "email_configured": mail is not None,
        "timestamp": datetime.now().isoformat()
    })

# ----------------------
# Debug route
# ----------------------
@app.route("/debug-info")
def debug_info():
    """Debug endpoint to see what files are available"""
    import os
    
    templates_folder = app.template_folder
    static_folder = app.static_folder
    
    templates_files = []
    if os.path.exists(templates_folder):
        templates_files = os.listdir(templates_folder)
    
    static_files = []
    if os.path.exists(static_folder):
        static_files = os.listdir(static_folder)
    
    return jsonify({
        "current_directory": os.getcwd(),
        "templates_folder": templates_folder,
        "templates_files": templates_files,
        "static_folder": static_folder,
        "static_files": static_files,
        "ml_models": os.listdir('ml') if os.path.exists('ml') else []
    })
@app.route("/api/latest-data", methods=['GET'])
def get_latest_data():
    if not latest_data_store:
        return jsonify({
            "temperature": 0,
            "current": 0,
            "breakerState": "Unknown",
            "systemStatus": "Waiting",
            "date": "",
            "time": ""
        })
    
    return jsonify(latest_data_store)
# ----------------------
# Run App
# ----------------------
if __name__ == "__main__":
    print("\n" + "="*50)
    print("Breaker Monitoring API Server")
    print("="*50)
    print(f"Templates folder: {app.template_folder}")
    print(f"Static folder: {app.static_folder}")
    print("="*50)
    print(f"Server running on: http://127.0.0.1:5000")
    print(f"Dashboard: http://127.0.0.1:5000/")
    print(f"API Health: http://127.0.0.1:5000/api/health")
    print(f"Debug Info: http://127.0.0.1:5000/debug-info")
    print("="*50 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)