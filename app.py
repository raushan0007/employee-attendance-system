# app.py - Enhanced Attendance System with City Location, Multiple Charts, and Edit Features
from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
import os
import json
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
import shutil
import schedule
import threading
import time
import requests

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "supersecretkey")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Setup logging
if not os.path.exists('logs'):
    os.makedirs('logs')
if not os.path.exists('backups'):
    os.makedirs('backups')
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

file_handler = RotatingFileHandler('logs/attendance.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Attendance system startup')

db = SQLAlchemy(app)

# ---------------- Enhanced Models ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    gender = db.Column(db.String(10))
    date_of_birth = db.Column(db.Date)
    week_off = db.Column(db.String(20), default='Sunday')
    current_status = db.Column(db.String(200), default='Available')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    department = db.Column(db.String(100), default='General')
    designation = db.Column(db.String(100), default='Employee')
    profile_picture = db.Column(db.String(200))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    login_time = db.Column(db.Time, default=datetime.strptime('09:00', '%H:%M').time())
    logout_time = db.Column(db.Time, default=datetime.strptime('19:00', '%H:%M').time())

    attendances = db.relationship('Attendance', back_populates='user', cascade="all, delete-orphan")
    leaves = db.relationship('Leave', back_populates='user', foreign_keys='Leave.user_id', cascade="all, delete-orphan")
    approved_leaves = db.relationship('Leave', back_populates='approver', foreign_keys='Leave.approved_by')
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', back_populates='sender')
    received_messages = db.relationship('Message', foreign_keys='Message.receiver_id', back_populates='receiver')
    notifications = db.relationship('Notification', back_populates='user')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    check_in = db.Column(db.Time)
    lunch_start = db.Column(db.Time)
    lunch_end = db.Column(db.Time)
    check_out = db.Column(db.Time)
    location = db.Column(db.String(300))
    latitude = db.Column(db.String(50))
    longitude = db.Column(db.String(50))
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    country = db.Column(db.String(100))
    status = db.Column(db.String(30), default='absent')
    total_hours = db.Column(db.Float, default=0.0)
    ip_address = db.Column(db.String(50))
    device_info = db.Column(db.String(200))
    notes = db.Column(db.Text)
    is_late = db.Column(db.Boolean, default=False)
    overtime_hours = db.Column(db.Float, default=0.0)
    extra_work_hours = db.Column(db.Float, default=0.0)

    user = db.relationship('User', back_populates='attendances')

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    leave_type = db.Column(db.String(80), nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.String(30), default='pending')
    applied_date = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    approved_date = db.Column(db.DateTime, nullable=True)
    emergency_contact = db.Column(db.String(100))
    attachment = db.Column(db.String(200))
    reject_reason = db.Column(db.Text)

    user = db.relationship('User', back_populates='leaves', foreign_keys=[user_id])
    approver = db.relationship('User', back_populates='approved_leaves', foreign_keys=[approved_by])

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    attachment = db.Column(db.String(200))

    sender = db.relationship('User', foreign_keys=[sender_id], back_populates='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], back_populates='received_messages')

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    type = db.Column(db.String(50))
    priority = db.Column(db.String(20), default='normal')  # low, normal, high, urgent

    user = db.relationship('User', back_populates='notifications')

# Create DB
with app.app_context():
    db.create_all()

# ---------------- Geolocation Functions ----------------
def get_city_from_coords(lat, lng):
    """Get city name from latitude and longitude using OpenStreetMap Nominatim API"""
    try:
        if not lat or not lng:
            return "Location not available"
        
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}&zoom=10"
        headers = {
            'User-Agent': 'AttendancePro System/1.0 (contact@company.com)'
        }
        
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            address = data.get('address', {})
            
            city = address.get('city') or address.get('town') or address.get('village') or address.get('county')
            state = address.get('state')
            country = address.get('country')
            
            location_parts = []
            if city:
                location_parts.append(city)
            if state:
                location_parts.append(state)
            if country:
                location_parts.append(country)
            
            return ", ".join(location_parts) if location_parts else "Unknown location"
        else:
            return f"Lat: {lat}, Lng: {lng}"
    except Exception as e:
        logging.error(f"Geocoding error: {str(e)}")
        return f"Lat: {lat}, Lng: {lng}"

def get_location_details(lat, lng):
    """Get detailed location information including city, state, country"""
    try:
        if not lat or not lng:
            return {"city": "Unknown", "state": "Unknown", "country": "Unknown"}
        
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}&zoom=10"
        headers = {
            'User-Agent': 'AttendancePro System/1.0 (contact@company.com)'
        }
        
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            address = data.get('address', {})
            
            return {
                "city": address.get('city') or address.get('town') or address.get('village') or address.get('county') or "Unknown",
                "state": address.get('state') or "Unknown",
                "country": address.get('country') or "Unknown"
            }
        else:
            return {"city": "Unknown", "state": "Unknown", "country": "Unknown"}
    except Exception as e:
        logging.error(f"Detailed geocoding error: {str(e)}")
        return {"city": "Unknown", "state": "Unknown", "country": "Unknown"}

# ---------------- Database Backup System ----------------
def backup_database():
    """Create automated database backups"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backups/attendance_{timestamp}.db"
        
        shutil.copy2('attendance.db', backup_file)
        
        # Keep only last 30 backups
        backups = sorted([f for f in os.listdir('backups') if f.endswith('.db')])
        if len(backups) > 30:
            for old_backup in backups[:-30]:
                os.remove(f"backups/{old_backup}")
        
        app.logger.info(f"Database backup created: {backup_file}")
    except Exception as e:
        app.logger.error(f"Backup failed: {str(e)}")

def start_backup_scheduler():
    """Start automated backup scheduler"""
    schedule.every().day.at("02:00").do(backup_database)
    
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    thread = threading.Thread(target=run_scheduler, daemon=True)
    thread.start()

# ---------------- Birthday Notification System ----------------
def check_birthdays():
    """Check and send birthday notifications"""
    today = date.today()
    birthday_users = User.query.filter(
        db.extract('month', User.date_of_birth) == today.month,
        db.extract('day', User.date_of_birth) == today.day,
        User.is_active == True
    ).all()
    
    for user in birthday_users:
        send_notification(user.id, "🎉 Happy Birthday!", 
                         f"Wishing you a fantastic birthday, {user.name}! Enjoy your special day!", 
                         'birthday', 'high')
        
        # Notify admin about birthdays
        admin = User.query.filter_by(role='admin').first()
        if admin:
            send_notification(admin.id, "Birthday Alert", 
                             f"Today is {user.name}'s birthday! 🎂", 
                             'birthday', 'normal')

def start_birthday_scheduler():
    """Start birthday check scheduler"""
    schedule.every().day.at("09:00").do(check_birthdays)

# ---------------- Notification System ----------------
def send_notification(user_id, title, message, notif_type='system', priority='normal'):
    """Send notification to user"""
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        type=notif_type,
        priority=priority
    )
    db.session.add(notification)
    db.session.commit()
    
    # Emit real-time notification via SocketIO
    socketio.emit('new_notification', {
        'id': notification.id,
        'title': title,
        'message': message,
        'type': notif_type,
        'priority': priority,
        'timestamp': datetime.utcnow().isoformat()
    }, room=f"user_{user_id}")

# ---------------- Context Processor ----------------
@app.context_processor
def inject_now():
    return {'date': date, 'datetime': datetime, 'today': date.today()}

@app.context_processor
def inject_notification_count():
    """Inject unread notification count into all templates"""
    if 'user_id' in session:
        user_id = session['user_id']
        unread_count = Notification.query.filter_by(
            user_id=user_id, 
            is_read=False
        ).count()
        return {'unread_notifications_count': unread_count}
    return {'unread_notifications_count': 0}

# ---------------- Helpers ----------------
def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kw):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        user = db.session.get(User, session['user_id'])
        if not user or not user.is_active:
            session.clear()
            flash('Your session is invalid or account is inactive. Please log in again.', 'danger')
            return redirect(url_for('login'))
            
        return f(*args, **kw)
    return wrapper

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kw):
        if 'user_id' not in session:
            return redirect(url_for('login'))
            
        user = db.session.get(User, session['user_id'])
        if not user or not user.is_active:
            session.clear()
            flash('Your session is invalid or account is inactive. Please log in again.', 'danger')
            return redirect(url_for('login'))
            
        if user.role != 'admin':
            flash('Access denied. Admin privileges required.', 'danger')
            return redirect(url_for('employee_dashboard'))
        return f(*args, **kw)
    return wrapper

def get_week_dates():
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    dates = [start_of_week + timedelta(days=i) for i in range(7)]
    return dates

def get_month_dates():
    today = date.today()
    first_day = today.replace(day=1)
    next_month = first_day.replace(month=first_day.month+1) if first_day.month < 12 else first_day.replace(year=first_day.year+1, month=1)
    last_day = next_month - timedelta(days=1)
    
    dates = []
    current = first_day
    while current <= last_day:
        dates.append(current)
        current += timedelta(days=1)
    return dates

def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

def get_user_activity_stats():
    today = date.today()
    week_dates = get_week_dates()
    month_dates = get_month_dates()
    
    total_users = User.query.filter_by(is_active=True).count()
    present_today = Attendance.query.filter_by(date=today, status='present').count()
    
    on_leave_today = Leave.query.filter(
        Leave.start_date <= today,
        Leave.end_date >= today,
        Leave.status == 'approved'
    ).count()
    
    pending_leaves = Leave.query.filter_by(status='pending').count()
    
    # Calculate late arrivals (check-in after 10:00 AM)
    late_arrivals = db.session.query(Attendance).filter(
        Attendance.date == today,
        Attendance.check_in.isnot(None),
        Attendance.check_in > datetime.strptime('10:00', '%H:%M').time()
    ).count()
    
    # Calculate extra working hours (after 7:00 PM)
    extra_work_today = db.session.query(Attendance).filter(
        Attendance.date == today,
        Attendance.check_out.isnot(None),
        Attendance.check_out > datetime.strptime('19:00', '%H:%M').time()
    ).count()
    
    weekly_data = []
    for day in week_dates:
        day_att = Attendance.query.filter_by(date=day, status='present').count()
        weekly_data.append(day_att)
    
    monthly_data = []
    for day in month_dates:
        day_att = Attendance.query.filter_by(date=day, status='present').count()
        monthly_data.append(day_att)
    
    departments = db.session.query(User.department, db.func.count(User.id))\
        .filter(User.is_active == True, User.role == 'employee')\
        .group_by(User.department).all()
    
    department_data = [{'name': dept[0], 'count': dept[1]} for dept in departments]
    
    leave_stats = db.session.query(Leave.status, db.func.count(Leave.id))\
        .group_by(Leave.status).all()
    leave_data = {stat[0]: stat[1] for stat in leave_stats}
    
    return {
        'total_users': total_users,
        'present_today': present_today,
        'on_leave_today': on_leave_today,
        'pending_leaves': pending_leaves,
        'late_arrivals': late_arrivals,
        'extra_work_today': extra_work_today,
        'weekly_data': weekly_data,
        'monthly_data': monthly_data,
        'department_data': department_data,
        'leave_data': leave_data
    }

def calculate_productivity(user_id, start_date, end_date):
    attendances = Attendance.query.filter(
        Attendance.user_id == user_id,
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).all()
    
    total_days = (end_date - start_date).days + 1
    present_days = len([att for att in attendances if att.status == 'present'])
    absent_days = len([att for att in attendances if att.status == 'absent'])
    half_days = len([att for att in attendances if att.status == 'half-day'])
    
    total_hours = sum([att.total_hours for att in attendances if att.total_hours])
    avg_hours_per_day = total_hours / present_days if present_days > 0 else 0
    
    # Calculate late arrivals and extra work
    late_count = len([att for att in attendances if att.is_late])
    extra_work_hours = sum([att.extra_work_hours for att in attendances if att.extra_work_hours])
    
    return {
        'total_days': total_days,
        'present_days': present_days,
        'absent_days': absent_days,
        'half_days': half_days,
        'attendance_percentage': (present_days / total_days * 100) if total_days > 0 else 0,
        'total_hours': total_hours,
        'avg_hours_per_day': avg_hours_per_day,
        'late_count': late_count,
        'extra_work_hours': extra_work_hours
    }

# Custom Jinja2 filters
@app.template_filter('date')
def format_date(value, format='%Y-%m-%d'):
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            return value
    return value.strftime(format)

@app.template_filter('datetime')
def format_datetime(value, format='%Y-%m-%d %H:%M:%S'):
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return value
    return value.strftime(format)

@app.template_filter('time')
def format_time(value, format='%H:%M'):
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, '%H:%M:%S').time()
        except ValueError:
            return value
    return value.strftime(format)

# ---------------- SocketIO Events ----------------
@socketio.on('connect')
def handle_connect():
    user_id = session.get('user_id')
    if user_id:
        join_room(f"user_{user_id}")
        user = db.session.get(User, user_id)
        if user:
            user.last_seen = datetime.utcnow()
            db.session.commit()
        emit('connection_status', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    user_id = session.get('user_id')
    if user_id:
        user = db.session.get(User, user_id)
        if user:
            user.last_seen = datetime.utcnow()
            db.session.commit()

@socketio.on('send_message')
def handle_send_message(data):
    user_id = session.get('user_id')
    if not user_id:
        emit('error', {'message': 'Not authenticated'})
        return
    
    try:
        receiver_id = data.get('receiver_id')
        message_text = data.get('message', '').strip()
        
        if not receiver_id or not message_text:
            emit('error', {'message': 'Invalid message data'})
            return
        
        # Check if receiver exists
        receiver = User.query.filter_by(id=receiver_id, is_active=True).first()
        if not receiver:
            emit('error', {'message': 'Receiver not found'})
            return
        
        message = Message(
            sender_id=user_id,
            receiver_id=receiver_id,
            message=message_text
        )
        db.session.add(message)
        db.session.commit()
        
        # Prepare response data
        response_data = {
            'id': message.id,
            'message': message_text,
            'sender_id': user_id,
            'sender_name': session.get('user_name'),
            'timestamp': datetime.utcnow().isoformat(),
            'is_read': False
        }
        
        # Emit to receiver
        emit('receive_message', response_data, room=f"user_{receiver_id}")
        
        # Emit confirmation to sender
        emit('message_sent', {
            'status': 'success',
            'message_id': message.id,
            'timestamp': response_data['timestamp']
        })
        
    except Exception as e:
        app.logger.error(f"Error sending message: {str(e)}")
        emit('error', {'message': 'Failed to send message'})

@socketio.on('mark_notification_read')
def handle_mark_notification_read(data):
    notification = db.session.get(Notification, data['notification_id'])
    if notification and notification.user_id == session.get('user_id'):
        notification.is_read = True
        db.session.commit()

# ---------------- Notification Routes ----------------
@app.route('/mark_notification_read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """Mark a single notification as read"""
    notification = db.session.get(Notification, notification_id)
    if notification and notification.user_id == session['user_id']:
        notification.is_read = True
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Notification not found'}), 404

@app.route('/mark_notifications_read', methods=['POST'])
@login_required
def mark_notifications_read():
    """Mark multiple notifications as read"""
    data = request.get_json()
    if not data or 'notification_ids' not in data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400
    
    notification_ids = data['notification_ids']
    user_id = session['user_id']
    
    # Mark notifications as read
    notifications = Notification.query.filter(
        Notification.id.in_(notification_ids),
        Notification.user_id == user_id
    ).all()
    
    for notification in notifications:
        notification.is_read = True
    
    db.session.commit()
    return jsonify({'success': True, 'message': f'{len(notifications)} notifications marked as read'})

@app.route('/mark_all_notifications_read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    """Mark all notifications as read for the current user"""
    user_id = session['user_id']
    updated_count = Notification.query.filter_by(
        user_id=user_id, 
        is_read=False
    ).update({'is_read': True})
    
    db.session.commit()
    return jsonify({'success': True, 'message': f'All notifications marked as read', 'updated_count': updated_count})

@app.route('/delete_notification/<int:notification_id>', methods=['POST'])
@login_required
def delete_notification(notification_id):
    """Delete a single notification"""
    notification = db.session.get(Notification, notification_id)
    if notification and notification.user_id == session['user_id']:
        db.session.delete(notification)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Notification deleted successfully'})
    return jsonify({'success': False, 'message': 'Notification not found'}), 404

@app.route('/delete_notifications', methods=['POST'])
@login_required
def delete_notifications():
    """Delete multiple notifications"""
    data = request.get_json()
    if not data or 'notification_ids' not in data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400
    
    notification_ids = data['notification_ids']
    user_id = session['user_id']
    
    # Delete notifications
    notifications = Notification.query.filter(
        Notification.id.in_(notification_ids),
        Notification.user_id == user_id
    ).all()
    
    deleted_count = 0
    for notification in notifications:
        db.session.delete(notification)
        deleted_count += 1
    
    db.session.commit()
    return jsonify({'success': True, 'message': f'{deleted_count} notifications deleted successfully'})

# ---------------- Chat Routes ----------------
@app.route('/get_unread_message_count')
@login_required
def get_unread_message_count():
    """Get unread message count for the current user"""
    user_id = session['user_id']
    unread_count = Message.query.filter_by(
        receiver_id=user_id, 
        is_read=False
    ).count()
    
    return jsonify({
        'success': True, 
        'unread_count': unread_count
    })

@app.route('/get_chat_users')
@login_required
def get_chat_users():
    """Get list of users for chat"""
    current_user_id = session['user_id']
    users = User.query.filter(
        User.id != current_user_id, 
        User.is_active == True
    ).all()
    
    users_data = []
    for user in users:
        # Get last message and unread count for each user
        last_message = Message.query.filter(
            ((Message.sender_id == current_user_id) & (Message.receiver_id == user.id)) |
            ((Message.sender_id == user.id) & (Message.receiver_id == current_user_id))
        ).order_by(Message.timestamp.desc()).first()
        
        unread_count = Message.query.filter_by(
            sender_id=user.id,
            receiver_id=current_user_id,
            is_read=False
        ).count()
        
        users_data.append({
            'id': user.id,
            'name': user.name,
            'username': user.username,
            'current_status': user.current_status,
            'last_seen': user.last_seen.isoformat() if user.last_seen else None,
            'last_message': last_message.message if last_message else None,
            'last_message_time': last_message.timestamp.isoformat() if last_message else None,
            'unread_count': unread_count
        })
    
    return jsonify({'success': True, 'users': users_data})

@app.route('/send_message', methods=['POST'])
@login_required
def send_message_api():
    """Send message via API (fallback for SocketIO)"""
    user_id = session['user_id']
    data = request.get_json()
    
    if not data or 'receiver_id' not in data or 'message' not in data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400
    
    receiver_id = data['receiver_id']
    message_text = data['message'].strip()
    
    if not message_text:
        return jsonify({'success': False, 'message': 'Message cannot be empty'}), 400
    
    # Check if receiver exists and is active
    receiver = User.query.filter_by(id=receiver_id, is_active=True).first()
    if not receiver:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    # Create message
    message = Message(
        sender_id=user_id,
        receiver_id=receiver_id,
        message=message_text
    )
    
    db.session.add(message)
    db.session.commit()
    
    # Emit via SocketIO if possible
    socketio.emit('receive_message', {
        'id': message.id,
        'message': message_text,
        'sender_id': user_id,
        'sender_name': session.get('user_name'),
        'timestamp': datetime.utcnow().isoformat()
    }, room=f"user_{receiver_id}")
    
    return jsonify({
        'success': True, 
        'message': 'Message sent successfully',
        'message_id': message.id
    })

@app.route('/mark_messages_read/<int:sender_id>', methods=['POST'])
@login_required
def mark_messages_read(sender_id):
    """Mark all messages from a sender as read"""
    user_id = session['user_id']
    
    messages = Message.query.filter_by(
        sender_id=sender_id,
        receiver_id=user_id,
        is_read=False
    ).all()
    
    for message in messages:
        message.is_read = True
    
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': f'Marked {len(messages)} messages as read'
    })

# ---------------- Routes ----------------
@app.route('/')
def home():
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user and user.is_active:
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('employee_dashboard'))
        else:
            session.clear()
            flash('Your session is invalid or account is inactive. Please log in again.', 'danger')
            return redirect(url_for('login'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username'].strip()
        p = request.form['password']
        user = User.query.filter_by(username=u, is_active=True).first()
        if user and check_password_hash(user.password, p):
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['user_name'] = user.name
            session['username'] = user.username
            
            # Update last seen
            user.last_seen = datetime.utcnow()
            db.session.commit()
            
            app.logger.info(f"User {user.username} logged in from IP: {get_client_ip()}")
            
            flash('Welcome back, ' + user.name, 'success')
            return redirect(url_for('home'))
        flash('Invalid credentials or account inactive', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'user_name' in session:
        app.logger.info(f"User {session['user_name']} logged out")
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))

@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    user = db.session.get(User, session['user_id'])
    stats = get_user_activity_stats()
    today = date.today()
    week_dates = get_week_dates()
    month_dates = get_month_dates()
    
    # Enhanced chart data
    # 1. Department-wise attendance for today
    departments = db.session.query(User.department).filter(User.is_active == True).distinct().all()
    dept_attendance_today = []
    for dept in departments:
        dept_name = dept[0]
        present_count = db.session.query(Attendance).join(User).filter(
            Attendance.date == today,
            Attendance.status == 'present',
            User.department == dept_name
        ).count()
        dept_attendance_today.append({
            'department': dept_name,
            'present': present_count
        })
    
    # 2. Weekly attendance trend by department
    weekly_dept_data = {}
    for dept in departments:
        dept_name = dept[0]
        weekly_data = []
        for day in week_dates:
            day_count = db.session.query(Attendance).join(User).filter(
                Attendance.date == day,
                Attendance.status == 'present',
                User.department == dept_name
            ).count()
            weekly_data.append(day_count)
        weekly_dept_data[dept_name] = weekly_data
    
    # 3. Monthly attendance summary
    current_month = today.month
    monthly_attendance = db.session.query(
        Attendance.date,
        db.func.count(Attendance.id).label('present_count')
    ).filter(
        db.extract('month', Attendance.date) == current_month,
        Attendance.status == 'present'
    ).group_by(Attendance.date).all()
    
    monthly_dates = [day for day in month_dates if day <= today]
    monthly_present = [0] * len(monthly_dates)
    
    for att in monthly_attendance:
        if att.date in monthly_dates:
            idx = monthly_dates.index(att.date)
            monthly_present[idx] = att.present_count
    
    # 4. Leave statistics by type
    leave_types = db.session.query(Leave.leave_type).distinct().all()
    leave_stats = {}
    for ltype in leave_types:
        type_name = ltype[0]
        approved_count = Leave.query.filter_by(leave_type=type_name, status='approved').count()
        pending_count = Leave.query.filter_by(leave_type=type_name, status='pending').count()
        rejected_count = Leave.query.filter_by(leave_type=type_name, status='rejected').count()
        leave_stats[type_name] = {
            'approved': approved_count,
            'pending': pending_count,
            'rejected': rejected_count
        }
    
    # 5. Employee location distribution today
    city_distribution = db.session.query(
        Attendance.city,
        db.func.count(Attendance.id).label('employee_count')
    ).filter(
        Attendance.date == today,
        Attendance.city.isnot(None)
    ).group_by(Attendance.city).all()
    
    # Get today's birthdays
    birthday_users = User.query.filter(
        db.extract('month', User.date_of_birth) == today.month,
        db.extract('day', User.date_of_birth) == today.day,
        User.is_active == True
    ).all()
    
    # Get unread notifications for dropdown
    unread_notifications = Notification.query.filter_by(
        user_id=user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(5).all()
    
    all_users = User.query.filter_by(is_active=True).all()
    user_status_data = []
    for usr in all_users:
        today_attendance = Attendance.query.filter_by(user_id=usr.id, date=today).first()
        
        # Check if user is working late
        is_working_late = False
        if today_attendance and today_attendance.check_out is None and datetime.now().time() > usr.logout_time:
            is_working_late = True
        
        user_status_data.append({
            'user': usr,
            'attendance': today_attendance,
            'current_location': today_attendance.location if today_attendance else 'Not available',
            'city': today_attendance.city if today_attendance else 'Unknown',
            'productivity': calculate_productivity(usr.id, today.replace(day=1), today),
            'is_working_late': is_working_late
        })
    
    recent_attendance = Attendance.query.filter(Attendance.date >= today - timedelta(days=7))\
        .order_by(Attendance.date.desc(), Attendance.check_in.desc()).limit(15).all()
    
    recent_leaves = Leave.query.filter(Leave.applied_date >= today - timedelta(days=30))\
        .order_by(Leave.applied_date.desc()).limit(10).all()
    
    # Get late arrivals today
    late_arrivals_today = Attendance.query.filter(
        Attendance.date == today,
        Attendance.check_in.isnot(None),
        Attendance.check_in > datetime.strptime('10:00', '%H:%M').time()
    ).all()
    
    # Get employees working extra today
    extra_work_today = Attendance.query.filter(
        Attendance.date == today,
        Attendance.check_out.isnot(None),
        Attendance.check_out > datetime.strptime('19:00', '%H:%M').time()
    ).all()
    
    week_labels = [d.strftime('%a') for d in week_dates]
    month_labels = [d.strftime('%d') for d in month_dates]
    
    return render_template('admin_dashboard.html', 
                         stats=stats,
                         user_status_data=user_status_data,
                         recent_attendance=recent_attendance,
                         recent_leaves=recent_leaves,
                         week_labels=week_labels,
                         week_data=stats['weekly_data'],
                         month_labels=month_labels,
                         month_data=stats['monthly_data'],
                         dept_data=stats['department_data'],
                         leave_data=stats['leave_data'],
                         birthday_users=birthday_users,
                         unread_notifications=unread_notifications,
                         late_arrivals_today=late_arrivals_today,
                         extra_work_today=extra_work_today,
                         dept_attendance_today=dept_attendance_today,
                         weekly_dept_data=weekly_dept_data,
                         monthly_dates=[d.strftime('%d') for d in monthly_dates if d <= today],
                         monthly_present=monthly_present,
                         leave_stats=leave_stats,
                         city_distribution=city_distribution,
                         today=today)

@app.route('/employee/dashboard')
@login_required
def employee_dashboard():
    user = db.session.get(User, session['user_id'])
    if user.role != 'employee':
        flash('Access denied', 'danger')
        return redirect(url_for('home'))
    
    today = date.today()
    attendance_today = Attendance.query.filter_by(user_id=user.id, date=today).first()
    
    # Check if user is working late
    is_working_late = False
    if attendance_today and attendance_today.check_out is None and datetime.now().time() > user.logout_time:
        is_working_late = True
    
    # Get unread notifications for dropdown
    unread_notifications = Notification.query.filter_by(
        user_id=user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(5).all()
    
    recent_att = Attendance.query.filter_by(user_id=user.id)\
        .order_by(Attendance.date.desc()).limit(7).all()
    
    leaves = Leave.query.filter_by(user_id=user.id)\
        .order_by(Leave.start_date.desc()).limit(5).all()
    
    month_start = today.replace(day=1)
    month_attendance = Attendance.query.filter(
        Attendance.user_id == user.id,
        Attendance.date >= month_start,
        Attendance.date <= today
    ).all()
    
    present_count = len([att for att in month_attendance if att.status == 'present'])
    absent_count = len([att for att in month_attendance if att.status == 'absent'])
    half_day_count = len([att for att in month_attendance if att.status == 'half-day'])
    total_hours = sum([att.total_hours for att in month_attendance if att.total_hours])
    late_count = len([att for att in month_attendance if att.is_late])
    extra_work_hours = sum([att.extra_work_hours for att in month_attendance if att.extra_work_hours])
    
    week_dates = get_week_dates()
    weekly_hours = []
    for day in week_dates:
        att = Attendance.query.filter_by(user_id=user.id, date=day).first()
        weekly_hours.append(att.total_hours if att and att.total_hours else 0)
    
    month_dates = get_month_dates()
    monthly_status = []
    for day in month_dates:
        if day > today:
            monthly_status.append(None)
            continue
        att = Attendance.query.filter_by(user_id=user.id, date=day).first()
        if att:
            if att.status == 'present':
                monthly_status.append(1)
            elif att.status == 'half-day':
                monthly_status.append(0.5)
            else:
                monthly_status.append(0)
        else:
            monthly_status.append(0)
    
    week_labels = [d.strftime('%a') for d in week_dates]
    month_labels = [d.strftime('%d') for d in month_dates if d <= today]
    
    return render_template('employee_dashboard.html', 
                         user=user, 
                         attendance_today=attendance_today,
                         recent_att=recent_att,
                         leaves=leaves,
                         present_count=present_count,
                         absent_count=absent_count,
                         half_day_count=half_day_count,
                         total_hours=total_hours,
                         late_count=late_count,
                         extra_work_hours=extra_work_hours,
                         week_labels=week_labels,
                         weekly_hours=weekly_hours,
                         month_labels=month_labels[:len(monthly_status)],
                         monthly_status=monthly_status,
                         unread_notifications=unread_notifications,
                         is_working_late=is_working_late,
                         today=today)

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
@admin_required
def users_management():
    if request.method == 'POST':
        name = request.form['name'].strip()
        username = request.form['username'].strip()
        password = request.form['password']
        email = request.form['email'].strip()
        phone = request.form.get('phone','').strip()
        role = request.form.get('role', 'employee')
        gender = request.form.get('gender', 'Other')
        dob = request.form.get('date_of_birth')
        week_off = request.form.get('week_off', 'Sunday')
        department = request.form.get('department', 'General')
        designation = request.form.get('designation', 'Employee')
        login_time = request.form.get('login_time', '09:00')
        logout_time = request.form.get('logout_time', '19:00')
        
        date_of_birth = datetime.strptime(dob, '%Y-%m-%d').date() if dob else None
        login_time_obj = datetime.strptime(login_time, '%H:%M').time()
        logout_time_obj = datetime.strptime(logout_time, '%H:%M').time()
        
        if User.query.filter((User.username==username)|(User.email==email)).first():
            flash('Username or email already exists', 'danger')
        else:
            hashed = generate_password_hash(password)
            new_user = User(
                username=username, 
                password=hashed, 
                role=role, 
                name=name, 
                email=email, 
                phone=phone,
                gender=gender,
                date_of_birth=date_of_birth,
                week_off=week_off,
                department=department,
                designation=designation,
                login_time=login_time_obj,
                logout_time=logout_time_obj
            )
            db.session.add(new_user)
            db.session.commit()
            
            send_notification(new_user.id, "Welcome!", f"Welcome to AttendancePro, {name}!", 'welcome', 'high')
            
            app.logger.info(f"New user created: {username} by {session['user_name']}")
            flash(f'{role.capitalize()} user added successfully', 'success')
            return redirect(url_for('users_management'))
    
    all_users = User.query.order_by(User.is_active.desc(), User.name.asc()).all()
    
    # Get unread notifications for dropdown
    user = db.session.get(User, session['user_id'])
    unread_notifications = Notification.query.filter_by(
        user_id=user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(5).all()
    
    return render_template('users_management.html', users=all_users, unread_notifications=unread_notifications)

@app.route('/admin/user/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    edit_user = db.session.get(User, user_id)
    if not edit_user:
        flash('User not found', 'danger')
        return redirect(url_for('users_management'))
    
    if request.method == 'POST':
        edit_user.name = request.form['name'].strip()
        edit_user.email = request.form['email'].strip()
        edit_user.phone = request.form.get('phone','').strip()
        edit_user.gender = request.form.get('gender', 'Other')
        edit_user.role = request.form.get('role', 'employee')
        edit_user.week_off = request.form.get('week_off', 'Sunday')
        edit_user.department = request.form.get('department', 'General')
        edit_user.designation = request.form.get('designation', 'Employee')
        edit_user.current_status = request.form.get('current_status', 'Available')
        
        # Update login/logout times
        login_time = request.form.get('login_time')
        logout_time = request.form.get('logout_time')
        if login_time:
            edit_user.login_time = datetime.strptime(login_time, '%H:%M').time()
        if logout_time:
            edit_user.logout_time = datetime.strptime(logout_time, '%H:%M').time()
        
        dob = request.form.get('date_of_birth')
        if dob:
            edit_user.date_of_birth = datetime.strptime(dob, '%Y-%m-%d').date()
        
        new_password = request.form.get('new_password')
        if new_password:
            edit_user.password = generate_password_hash(new_password)
        
        db.session.commit()
        app.logger.info(f"User {edit_user.username} updated by {session['user_name']}")
        flash('User updated successfully', 'success')
        return redirect(url_for('users_management'))
    
    # Get unread notifications for dropdown
    user = db.session.get(User, session['user_id'])
    unread_notifications = Notification.query.filter_by(
        user_id=user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(5).all()
    
    return render_template('edit_user.html', edit_user=edit_user, unread_notifications=unread_notifications)

@app.route('/admin/user/<int:user_id>/toggle_status')
@login_required
@admin_required
def toggle_user_status(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('users_management'))
        
    user.is_active = not user.is_active
    db.session.commit()
    
    status = "activated" if user.is_active else "deactivated"
    app.logger.info(f"User {user.username} {status} by {session['user_name']}")
    flash(f'User {status} successfully', 'success')
    return redirect(url_for('users_management'))

@app.route('/leaves')
@login_required
def leaves():
    user = db.session.get(User, session['user_id'])
    
    # Get unread notifications for dropdown
    unread_notifications = Notification.query.filter_by(
        user_id=user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(5).all()
    
    if user.role == 'admin':
        all_leaves = Leave.query.order_by(Leave.applied_date.desc()).all()
        return render_template('leaves.html', leaves=all_leaves, is_admin=True, User=User, unread_notifications=unread_notifications)
    else:
        user_leaves = Leave.query.filter_by(user_id=user.id)\
            .order_by(Leave.applied_date.desc()).all()
        return render_template('leaves.html', leaves=user_leaves, is_admin=False, User=User, unread_notifications=unread_notifications)

@app.route('/apply_leave', methods=['POST'])
@login_required
def apply_leave():
    uid = session['user_id']
    start = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
    end = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
    ltype = request.form['leave_type']
    reason = request.form.get('reason','')
    emergency_contact = request.form.get('emergency_contact', '')
    
    if start > end:
        flash('End date should be after start date', 'danger')
        return redirect(url_for('leaves'))
    
    if start < date.today():
        flash('Cannot apply leave for past dates', 'danger')
        return redirect(url_for('leaves'))
    
    conflicting_leaves = Leave.query.filter(
        Leave.user_id == uid,
        Leave.status == 'approved',
        ((Leave.start_date <= start) & (Leave.end_date >= start)) |
        ((Leave.start_date <= end) & (Leave.end_date >= end)) |
        ((Leave.start_date >= start) & (Leave.end_date <= end))
    ).first()
    
    if conflicting_leaves:
        flash('You already have approved leaves for the selected dates', 'danger')
        return redirect(url_for('leaves'))
    
    new_leave = Leave(
        user_id=uid, 
        start_date=start, 
        end_date=end, 
        leave_type=ltype, 
        reason=reason, 
        emergency_contact=emergency_contact,
        status='pending'
    )
    db.session.add(new_leave)
    db.session.commit()
    
    # Notify admin about new leave application
    admin = User.query.filter_by(role='admin').first()
    if admin:
        send_notification(admin.id, "New Leave Application", 
                         f"{session['user_name']} has applied for {ltype} leave from {start} to {end}", 
                         'leave', 'normal')
    
    app.logger.info(f"Leave applied by user {session['user_name']} from {start} to {end}")
    flash('Leave applied successfully (pending approval)', 'success')
    return redirect(url_for('leaves'))

@app.route('/admin/leave_action', methods=['POST'])
@login_required
@admin_required
def leave_action():
    lid = int(request.form['leave_id'])
    action = request.form['action']
    reject_reason = request.form.get('reject_reason', '')
    
    leave = db.session.get(Leave, lid)
    
    if not leave: 
        return jsonify({'success':False, 'message':'Leave not found'}), 404
    
    if action == 'approve': 
        leave.status = 'approved'
        leave.approved_by = session['user_id']
        leave.approved_date = datetime.utcnow()
        message = 'Leave approved successfully'
        
        # Notify employee
        send_notification(leave.user_id, "Leave Approved", 
                         f"Your {leave.leave_type} leave from {leave.start_date} to {leave.end_date} has been approved by {session['user_name']}",
                         'leave', 'normal')
    elif action == 'reject': 
        leave.status = 'rejected'
        leave.approved_by = session['user_id']
        leave.approved_date = datetime.utcnow()
        leave.reject_reason = reject_reason
        message = 'Leave rejected successfully'
        
        # Notify employee
        send_notification(leave.user_id, "Leave Rejected", 
                         f"Your {leave.leave_type} leave from {leave.start_date} to {leave.end_date} has been rejected by {session['user_name']}",
                         'leave', 'normal')
    else:
        return jsonify({'success':False, 'message':'Invalid action'}), 400
    
    db.session.commit()
    
    approver = db.session.get(User, session['user_id'])
    app.logger.info(f"Leave {action}ed by {session['user_name']} for user {leave.user.username}")
    
    return jsonify({
        'success': True, 
        'message': message,
        'approver_name': approver.name,
        'approval_date': leave.approved_date.strftime('%Y-%m-%d %H:%M:%S'),
        'reject_reason': leave.reject_reason if action == 'reject' else ''
    })

@app.route('/admin/reports')
@login_required
@admin_required
def reports():
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    employee_id = request.args.get('employee_id')
    report_type = request.args.get('report_type', 'attendance')
    
    if start and end:
        start_date = datetime.strptime(start, '%Y-%m-%d').date()
        end_date = datetime.strptime(end, '%Y-%m-%d').date()
    else:
        today = date.today()
        start_date = today.replace(day=1)
        end_date = today
    
    if report_type == 'attendance':
        query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date)
        
        if employee_id and employee_id != 'all':
            query = query.filter(Attendance.user_id == employee_id)
        
        report_data = query.order_by(Attendance.date.desc()).all()
        
        total_days = (end_date - start_date).days + 1
        present_days = len([att for att in report_data if att.status == 'present'])
        absent_days = len([att for att in report_data if att.status == 'absent'])
        half_days = len([att for att in report_data if att.status == 'half-day'])
        late_days = len([att for att in report_data if att.is_late])
        total_overtime = sum([att.overtime_hours for att in report_data if att.overtime_hours])
        attendance_percentage = (present_days / total_days * 100) if total_days > 0 else 0
        
        analytics = {
            'total_days': total_days,
            'present_days': present_days,
            'absent_days': absent_days,
            'half_days': half_days,
            'late_days': late_days,
            'total_overtime': round(total_overtime, 2),
            'attendance_percentage': round(attendance_percentage, 2)
        }
    else:
        query = Leave.query.filter(Leave.applied_date >= start_date, Leave.applied_date <= end_date)
        
        if employee_id and employee_id != 'all':
            query = query.filter(Leave.user_id == employee_id)
        
        report_data = query.order_by(Leave.applied_date.desc()).all()
        
        approved_leaves = len([leave for leave in report_data if leave.status == 'approved'])
        pending_leaves = len([leave for leave in report_data if leave.status == 'pending'])
        rejected_leaves = len([leave for leave in report_data if leave.status == 'rejected'])
        
        analytics = {
            'approved_leaves': approved_leaves,
            'pending_leaves': pending_leaves,
            'rejected_leaves': rejected_leaves,
            'total_leaves': len(report_data)
        }
    
    employees = User.query.filter_by(role='employee', is_active=True).all()
    
    # Get unread notifications for dropdown
    user = db.session.get(User, session['user_id'])
    unread_notifications = Notification.query.filter_by(
        user_id=user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(5).all()
    
    return render_template('reports.html', 
                         report_data=report_data,
                         start_date=start_date,
                         end_date=end_date,
                         employees=employees,
                         selected_employee=employee_id,
                         report_type=report_type,
                         analytics=analytics,
                         unread_notifications=unread_notifications)

@app.route('/mark_attendance', methods=['POST'])
@login_required
def mark_attendance():
    user_id = session['user_id']
    user = db.session.get(User, user_id)
    payload = request.get_json() or {}
    action = payload.get('action')
    latitude = payload.get('latitude')
    longitude = payload.get('longitude')
    location = payload.get('location', '')
    notes = payload.get('notes', '')
    
    today = date.today()
    attendance = Attendance.query.filter_by(user_id=user_id, date=today).first()
    
    if not attendance:
        attendance = Attendance(
            user_id=user_id, 
            date=today, 
            location=location, 
            latitude=latitude, 
            longitude=longitude,
            status='present',
            ip_address=get_client_ip(),
            device_info=request.headers.get('User-Agent', 'Unknown'),
            notes=notes
        )
        db.session.add(attendance)
    
    now = datetime.now().time()
    current_datetime = datetime.now()
    
    # Get location details including city
    if latitude and longitude:
        location_details = get_location_details(latitude, longitude)
        attendance.city = location_details['city']
        attendance.state = location_details['state']
        attendance.country = location_details['country']
        
        if not location:
            attendance.location = f"{location_details['city']}, {location_details['state']}, {location_details['country']}"
    
    if action == 'check_in':
        attendance.check_in = now
        
        # Check if late (after 10:00 AM)
        if now > datetime.strptime('10:00', '%H:%M').time():
            attendance.is_late = True
            # Notify admin about late arrival
            admin = User.query.filter_by(role='admin').first()
            if admin:
                location_str = f" in {attendance.city}" if attendance.city else ""
                send_notification(admin.id, "Late Arrival", 
                                f"{user.name} checked in late at {now.strftime('%H:%M')}{location_str}",
                                'attendance', 'normal')
        else:
            attendance.is_late = False
            
        attendance.status = 'present'
        user.current_status = 'Working'
        log_msg = f"Check-in recorded for {user.username}"
        
    elif action == 'lunch_start':
        attendance.lunch_start = now
        user.current_status = 'On Lunch Break'
        log_msg = f"Lunch start recorded for {user.username}"
        
    elif action == 'lunch_end':
        attendance.lunch_end = now
        user.current_status = 'Working'
        log_msg = f"Lunch end recorded for {user.username}"
        
    elif action == 'check_out':
        attendance.check_out = now
        
        # Calculate total hours
        if attendance.check_in:
            check_in_dt = datetime.combine(today, attendance.check_in)
            check_out_dt = datetime.combine(today, now)
            
            total_seconds = (check_out_dt - check_in_dt).total_seconds()
            if attendance.lunch_start and attendance.lunch_end:
                lunch_start_dt = datetime.combine(today, attendance.lunch_start)
                lunch_end_dt = datetime.combine(today, attendance.lunch_end)
                lunch_seconds = (lunch_end_dt - lunch_start_dt).total_seconds()
                total_seconds -= lunch_seconds
            
            attendance.total_hours = total_seconds / 3600
            
            # Calculate overtime (after 7:00 PM)
            if now > datetime.strptime('19:00', '%H:%M').time():
                end_of_day = datetime.combine(today, datetime.strptime('19:00', '%H:%M').time())
                overtime_seconds = (check_out_dt - end_of_day).total_seconds()
                attendance.overtime_hours = overtime_seconds / 3600
                
                # Notify admin about overtime
                admin = User.query.filter_by(role='admin').first()
                if admin:
                    location_str = f" in {attendance.city}" if attendance.city else ""
                    send_notification(admin.id, "Overtime Worked", 
                                    f"{user.name} worked overtime today ({attendance.overtime_hours:.2f} hours){location_str}",
                                    'attendance', 'normal')
        
        user.current_status = 'Available'
        log_msg = f"Check-out recorded for {user.username}"
    else:
        return jsonify({'success': False, 'message': 'Invalid action'}), 400
    
    db.session.commit()
    app.logger.info(log_msg)
    
    # Return location info in response
    response_data = {
        'success': True, 
        'message': f'{action.replace("_", " ").title()} recorded successfully',
        'city': attendance.city,
        'location': attendance.location
    }
    
    return jsonify(response_data)

@app.route('/set_status', methods=['POST'])
@login_required
def set_status():
    user = db.session.get(User, session['user_id'])
    payload = request.get_json() or {}
    new_status = payload.get('status','').strip()
    latitude = payload.get('latitude')
    longitude = payload.get('longitude')
    location = payload.get('location', '')
    
    user.current_status = new_status
    
    today = date.today()
    attendance_today = Attendance.query.filter_by(user_id=user.id, date=today).first()
    if attendance_today and latitude and longitude:
        attendance_today.latitude = latitude
        attendance_today.longitude = longitude
        if location:
            attendance_today.location = location
        else:
            attendance_today.location = get_city_from_coords(latitude, longitude)
    
    db.session.commit()
    app.logger.info(f"Status updated to '{new_status}' by {user.username}")
    return jsonify({'success':True, 'message':'Status updated successfully'})

@app.route('/chat')
@login_required
def chat():
    user = db.session.get(User, session['user_id'])
    users = User.query.filter(User.id != user.id, User.is_active == True).all()
    
    # Get unread notifications for dropdown
    unread_notifications = Notification.query.filter_by(
        user_id=user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(5).all()
    
    # Get unread message count
    unread_message_count = Message.query.filter_by(
        receiver_id=user.id, 
        is_read=False
    ).count()
    
    # Get recent conversations
    recent_conversations = db.session.query(
        User.id,
        User.name,
        User.username,
        User.current_status,
        db.func.max(Message.timestamp).label('last_message_time')
    ).join(
        Message, 
        ((Message.sender_id == User.id) & (Message.receiver_id == user.id)) |
        ((Message.sender_id == user.id) & (Message.receiver_id == User.id))
    ).filter(
        User.is_active == True,
        User.id != user.id
    ).group_by(User.id).order_by(db.desc('last_message_time')).all()
    
    return render_template('chat.html', 
                         users=users, 
                         recent_conversations=recent_conversations,
                         unread_message_count=unread_message_count,
                         unread_notifications=unread_notifications)

@app.route('/get_messages/<int:user_id>')
@login_required
def get_messages(user_id):
    current_user_id = session['user_id']
    messages = Message.query.filter(
        ((Message.sender_id == current_user_id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user_id))
    ).order_by(Message.timestamp.asc()).all()
    
    # Mark messages as read
    for msg in messages:
        if msg.receiver_id == current_user_id and not msg.is_read:
            msg.is_read = True
    db.session.commit()
    
    messages_data = []
    for msg in messages:
        messages_data.append({
            'id': msg.id,
            'sender_id': msg.sender_id,
            'sender_name': msg.sender.name,
            'message': msg.message,
            'timestamp': msg.timestamp.isoformat(),
            'is_read': msg.is_read
        })
    
    return jsonify({'success': True, 'messages': messages_data})

@app.route('/notifications')
@login_required
def notifications():
    user = db.session.get(User, session['user_id'])
    notifications = Notification.query.filter_by(user_id=user.id)\
        .order_by(Notification.created_at.desc()).all()
    
    # Get unread notifications for dropdown
    unread_notifications = Notification.query.filter_by(
        user_id=user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(5).all()
    
    return render_template('notifications.html', notifications=notifications, unread_notifications=unread_notifications)

@app.route('/admin/user_locations')
@login_required
@admin_required
def user_locations():
    today = date.today()
    locations = Attendance.query.filter(
        Attendance.date == today,
        Attendance.latitude.isnot(None),
        Attendance.longitude.isnot(None)
    ).all()
    
    location_data = []
    for att in locations:
        location_data.append({
            'user_id': att.user_id,
            'user_name': att.user.name,
            'username': att.user.username,
            'latitude': float(att.latitude) if att.latitude else None,
            'longitude': float(att.longitude) if att.longitude else None,
            'location': att.location,
            'city': att.city,
            'check_in_time': att.check_in.strftime('%H:%M') if att.check_in else 'Not checked in',
            'status': att.user.current_status,
            'department': att.user.department,
            'is_late': att.is_late
        })
    
    return jsonify({'success': True, 'locations': location_data})

@app.route('/api/dashboard_data')
@login_required
def dashboard_data():
    user = db.session.get(User, session['user_id'])
    
    if user.role == 'admin':
        stats = get_user_activity_stats()
        return jsonify({
            'weekly_data': stats['weekly_data'],
            'monthly_data': stats['monthly_data'],
            'department_data': stats['department_data'],
            'leave_data': stats['leave_data']
        })
    else:
        today = date.today()
        week_dates = get_week_dates()
        weekly_hours = []
        for day in week_dates:
            att = Attendance.query.filter_by(user_id=user.id, date=day).first()
            weekly_hours.append(att.total_hours if att and att.total_hours else 0)
        
        return jsonify({
            'weekly_hours': weekly_hours
        })

@app.route('/admin/edit_attendance/<int:attendance_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_attendance(attendance_id):
    attendance = db.session.get(Attendance, attendance_id)
    if not attendance:
        flash('Attendance record not found', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        try:
            # Update check-in time
            check_in_str = request.form.get('check_in')
            if check_in_str:
                attendance.check_in = datetime.strptime(check_in_str, '%H:%M').time()
            
            # Update check-out time
            check_out_str = request.form.get('check_out')
            if check_out_str:
                attendance.check_out = datetime.strptime(check_out_str, '%H:%M').time()
            
            # Update lunch times
            lunch_start_str = request.form.get('lunch_start')
            if lunch_start_str:
                attendance.lunch_start = datetime.strptime(lunch_start_str, '%H:%M').time()
            
            lunch_end_str = request.form.get('lunch_end')
            if lunch_end_str:
                attendance.lunch_end = datetime.strptime(lunch_end_str, '%H:%M').time()
            
            # Update status
            attendance.status = request.form.get('status', attendance.status)
            
            # Update notes
            attendance.notes = request.form.get('notes', attendance.notes)
            
            # Recalculate total hours if times are updated
            if attendance.check_in and attendance.check_out:
                check_in_dt = datetime.combine(attendance.date, attendance.check_in)
                check_out_dt = datetime.combine(attendance.date, attendance.check_out)
                
                total_seconds = (check_out_dt - check_in_dt).total_seconds()
                if attendance.lunch_start and attendance.lunch_end:
                    lunch_start_dt = datetime.combine(attendance.date, attendance.lunch_start)
                    lunch_end_dt = datetime.combine(attendance.date, attendance.lunch_end)
                    lunch_seconds = (lunch_end_dt - lunch_start_dt).total_seconds()
                    total_seconds -= lunch_seconds
                
                attendance.total_hours = total_seconds / 3600
            
            db.session.commit()
            
            # Log the edit action
            app.logger.info(f"Attendance record {attendance_id} edited by {session['user_name']}")
            flash('Attendance record updated successfully', 'success')
            return redirect(url_for('admin_dashboard'))
            
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error editing attendance: {str(e)}")
            flash('Error updating attendance record', 'danger')
    
    # Get unread notifications for dropdown
    user = db.session.get(User, session['user_id'])
    unread_notifications = Notification.query.filter_by(
        user_id=user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(5).all()
    
    return render_template('edit_attendance.html', 
                         attendance=attendance,
                         unread_notifications=unread_notifications)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

def create_admin_user():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin', 
            password=generate_password_hash('Raushan@1234!'), 
            role='admin', 
            name='Super Admin', 
            email='admin@company.com',
            department='Administration',
            designation='System Administrator',
            gender='Other'
        )
        db.session.add(admin)
        db.session.commit()
        app.logger.info("Default admin user created: admin/admin")
    else:
        admin.is_active = True
        db.session.commit()
        app.logger.info("Admin user verified and activated")

if __name__ == '__main__':
    with app.app_context():
        create_admin_user()
        start_backup_scheduler()
        start_birthday_scheduler()
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)