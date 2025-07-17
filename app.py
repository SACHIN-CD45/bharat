from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user, AnonymousUserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import os
from PIL import Image
import base64
import io
from dateutil.parser import parse
import uuid
import pytz  # Import pytz for time zone conversion
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail, Message

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'  # Change this to a secure secret key
app.config['MONGO_URI'] = 'mongodb://localhost:27017/gym_management'
app.config['UPLOAD_FOLDER'] = os.path.join(app.static_folder, 'uploads')
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your-email@gmail.com'  # Replace with your Gmail address
app.config['MAIL_PASSWORD'] = 'your-app-password'  # Replace with your Gmail App Password
app.config['MAIL_DEBUG'] = True

# Initialize MongoDB
mongo = PyMongo(app).db

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize URL serializer for generating secure tokens
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# Initialize Flask-Mail
mail = Mail(app)

# Create required directories if they don't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.static_folder, 'img'), exist_ok=True)

class User(UserMixin):
    def __init__(self, user_data):
        self.user_data = user_data
        self.id = str(user_data['_id'])
        
        # Ensure required fields exist with defaults
        if 'name' not in self.user_data:
            self.user_data['name'] = self.user_data.get('gym_name', 'User')
        if 'photo' not in self.user_data:
            self.user_data['photo'] = None
        if 'email' not in self.user_data:
            self.user_data['email'] = ''
        if 'gym_name' not in self.user_data:
            self.user_data['gym_name'] = 'My Gym'

class AnonymousUser(AnonymousUserMixin):
    @property
    def user_data(self):
        return {
            'gym_name': 'Guest',
            'name': 'Guest',
            'email': '',
            'photo': None,
            '_id': None
        }

login_manager.anonymous_user = AnonymousUser

@login_manager.user_loader
def load_user(user_id):
    try:
        user_data = mongo.db.gym_owners.find_one({'_id': ObjectId(user_id)})
        if user_data:
            return User(user_data)
        return None
    except:
        return None

@app.context_processor
def inject_notification_count():
    if current_user.is_authenticated:
        count = mongo.db.notifications.count_documents({
            'gym_owner_id': ObjectId(current_user.id),
            'is_read': False
        })
        return {'notification_count': count}
    return {'notification_count': 0}

@app.context_processor
def inject_year():
    return {'current_year': datetime.now().year}

def save_photo(photo_data):
    if not photo_data:
        return None
    
    # Remove the data URL prefix
    if 'base64,' in photo_data:
        photo_data = photo_data.split('base64,')[1]
    
    # Decode base64 data
    photo_binary = base64.b64decode(photo_data)
    
    # Generate a unique filename
    filename = f"{uuid.uuid4()}.jpg"
    
    # Save to static/uploads directory
    upload_path = os.path.join(app.static_folder, 'uploads', filename)
    os.makedirs(os.path.dirname(upload_path), exist_ok=True)
    
    with open(upload_path, 'wb') as f:
        f.write(photo_binary)
    
    return f"/static/uploads/{filename}"

@app.route('/')
def index():
    if current_user.is_authenticated:
        user_data = mongo.db.gym_owners.find_one({'_id': ObjectId(current_user.id)})
        if user_data.get('has_used_free_trial', False):
            trial_end_date = user_data.get('trial_start_date') + timedelta(days=15)
            if datetime.now() > trial_end_date:
                return redirect(url_for('subscription'))
        else:
            return redirect(url_for('subscription'))
    return render_template('index.html')

@app.route('/subscription')
@login_required
def subscription():
    # Redirect normal users away from the subscription page
    if current_user.user_data.get('role') == 'normal':
        flash('Subscription plans are not available for normal users.', 'info')
        return redirect(url_for('user_panel'))
    
    user_data = mongo.db.gym_owners.find_one({'_id': ObjectId(current_user.id)})
    if user_data.get('has_used_free_trial', False):
        trial_end_date = user_data.get('trial_start_date') + timedelta(days=15)
        if datetime.now() > trial_end_date:
            flash('Your free trial has expired. Please select a subscription plan.', 'warning')
        else:
            flash(f"Your free trial ends on {trial_end_date.strftime('%Y-%m-%d')}.", 'info')
    return render_template('subscription.html')

@app.route('/process_payment', methods=['POST'])
@login_required
def process_payment():
    plan = request.form.get('subscription_plan')
    if not plan:
        flash('No subscription plan selected.', 'danger')
        return redirect(url_for('subscription'))

    # Check if the user has already used the free trial
    if plan == 'free_trial':
        user_data = mongo.db.gym_owners.find_one({'_id': ObjectId(current_user.id)})
        if user_data.get('has_used_free_trial', False):
            flash('You have already used the free trial.', 'danger')
            return redirect(url_for('subscription'))

        # Mark the user as having used the free trial
        mongo.db.gym_owners.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {'has_used_free_trial': True, 'trial_start_date': datetime.now()}}
        )
        flash('Free trial activated successfully!', 'success')
        return redirect(url_for('dashboard'))

    # Handle subscription renewal
    duration_map = {
        'one_month': 30,
        'three_months': 90,
        'six_months': 180,
        'one_year': 365
    }
    if plan in duration_map:
        duration_days = duration_map[plan]
        user_data = mongo.db.gym_owners.find_one({'_id': ObjectId(current_user.id)})
        current_end = user_data.get('subscription_end', datetime.utcnow())
        new_end = max(current_end, datetime.utcnow()) + timedelta(days=duration_days)
        
        mongo.db.gym_owners.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {'subscription_end': new_end}}
        )
        flash('Subscription renewed successfully!', 'success')
        return redirect(url_for('dashboard'))

    flash('Invalid subscription plan selected.', 'danger')
    return redirect(url_for('subscription'))

@app.context_processor
def utility_processor():
    def enumerate_list(iterable, start=0):
        return enumerate(iterable, start)
    return dict(enumerate_list=enumerate_list)

@app.route('/dashboard')
@login_required
def dashboard():
    now = datetime.utcnow()
    week_from_now = now + timedelta(days=7)
    
    # Get active and expired members
    active_members = mongo.db.members.count_documents({
        'gym_owner_id': ObjectId(current_user.id),
        'membership_end': {'$gte': now}
    })
    
    expired_members = mongo.db.members.count_documents({
        'gym_owner_id': ObjectId(current_user.id),
        'membership_end': {'$lt': now}
    })
    
    # Get members expiring soon
    expiring_soon = mongo.db.members.count_documents({
        'gym_owner_id': ObjectId(current_user.id),
        'membership_end': {
            '$gte': now,
            '$lte': week_from_now
        }
    })
    
    # Get recent members
    recent_members = list(mongo.db.members.find({
        'gym_owner_id': ObjectId(current_user.id)
    }).sort('join_date', -1).limit(10))
    
    for member in recent_members:
        member['_id'] = str(member['_id'])
    
    # Get unread notifications
    notifications = list(mongo.db.notifications.find({
        'gym_owner_id': ObjectId(current_user.id),
        'is_read': False
    }).sort('created_at', -1))
    
    for notif in notifications:
        notif['_id'] = str(notif['_id'])
    
    # Calculate monthly earnings
    earnings = []
    for month in range(1, 13):
        start_date = datetime(now.year, month, 1)
        end_date = datetime(now.year, month + 1, 1) if month < 12 else datetime(now.year + 1, 1, 1)
        monthly_earnings = list(mongo.db.payments.aggregate([
            {'$match': {
                'gym_owner_id': ObjectId(current_user.id),
                'payment_date': {'$gte': start_date, '$lt': end_date}
            }},
            {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
        ]))
        earnings.append(monthly_earnings[0]['total'] if monthly_earnings else 0)
    
    return render_template('dashboard.html',
                         active_members=active_members,
                         expired_members=expired_members,
                         expiring_soon=expiring_soon,
                         members=recent_members,
                         notifications=notifications,
                         earnings=earnings,
                         now=now)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard') if current_user.user_data.get('role') == 'gym_owner' else url_for('user_panel'))
        
    if request.method == 'POST':
        role = request.form.get('role')  # Get the selected role
        gym_name = request.form.get('gym_name') if role == 'gym_owner' else None
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        photo_data = request.files.get('photo')
        
        if mongo.db.gym_owners.find_one({'email': email}):
            flash('Email already registered', 'danger')
            return redirect(url_for('signup'))
        
        # Save photo if provided
        photo_url = None
        if photo_data:
            filename = save_photo(photo_data.read())
            photo_url = filename
        
        # Hash password
        hashed_password = generate_password_hash(password)
        
        # Create user with all required fields
        user_data = {
            'role': role,  # Add role to user data
            'gym_name': gym_name if role == 'gym_owner' else None,
            'email': email,
            'password': hashed_password,
            'name': name or (gym_name if role == 'gym_owner' else 'User'),
            'photo': photo_url,
            'created_at': datetime.utcnow()
        }
        
        result = mongo.db.gym_owners.insert_one(user_data)
        user_data['_id'] = result.inserted_id
        
        # Log in the new user
        user = User(user_data)
        login_user(user)
        
        flash('Account created successfully!', 'success')
        return redirect(url_for('dashboard') if role == 'gym_owner' else url_for('user_panel'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard') if current_user.user_data.get('role') == 'gym_owner' else url_for('user_panel'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')  # Get the role from the form

        # Find the user by email and role
        user_data = mongo.db.gym_owners.find_one({'email': email, 'role': role})
        
        if user_data and check_password_hash(user_data['password'], password):
            user = User(user_data)
            login_user(user)
            
            next_page = request.args.get('next')
            return redirect(next_page or (url_for('dashboard') if role == 'gym_owner' else url_for('user_panel')))
        
        flash('Invalid email, password, or role selection', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user_data = mongo.db.gym_owners.find_one({'email': email})
        if user_data:
            token = serializer.dumps(email, salt='password-reset-salt')
            reset_url = url_for('reset_password', token=token, _external=True)
            
            # Send email using Gmail SMTP
            try:
                msg = Message(
                    'Password Reset Request',
                    sender=app.config['MAIL_USERNAME'],
                    recipients=[email]
                )
                msg.body = f"Hello,\n\nClick the link below to reset your password:\n{reset_url}\n\nIf you did not request this, please ignore this email."
                mail.send(msg)
                flash('A password reset link has been sent to your email.', 'info')
            except Exception as e:
                flash(f'Error sending email: {str(e)}', 'danger')
        else:
            flash('No account found with that email.', 'danger')
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='password-reset-salt', max_age=3600)  # Token valid for 1 hour
    except:
        flash('The password reset link is invalid or has expired.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('password')
        hashed_password = generate_password_hash(new_password)
        mongo.db.gym_owners.update_one({'email': email}, {'$set': {'password': hashed_password}})
        flash('Your password has been reset successfully!', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)

@app.route('/add_member', methods=['GET', 'POST'])
@login_required
def add_member():
    # Get list of trainers for the PT section
    trainers = list(mongo.db.trainers.find({'gym_owner_id': ObjectId(current_user.id)}))
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        address = request.form.get('address')
        membership_duration = int(request.form.get('duration'))
        photo_data = request.form.get('photo')
        
        # PT Information
        needs_pt = request.form.get('needs_pt') == 'on'
        trainer_id = request.form.get('trainer') if needs_pt else None
        pt_sessions = int(request.form.get('pt_sessions')) if needs_pt else None
        
        # Health Information
        weight = request.form.get('weight')
        height = request.form.get('height')
        health_conditions = request.form.get('health_conditions')
        
        # Emergency Contact
        emergency_contact_name = request.form.get('emergency_contact_name')
        emergency_contact_phone = request.form.get('emergency_contact_phone')
        
        # Check if member email already exists
        existing_member = mongo.db.members.find_one({
            'gym_owner_id': ObjectId(current_user.id),
            'email': email
        })
        
        if existing_member:
            flash('A member with this email already exists', 'danger')
            return redirect(url_for('add_member'))
        
        # Process photo if provided
        photo_filename = None
        if photo_data:
            photo_filename = save_photo(photo_data)
        
        # Add member to database
        member = {
            'name': name,
            'email': email,
            'phone': phone,
            'address': address,
            'join_date': datetime.utcnow(),
            'membership_end': datetime.utcnow() + timedelta(days=membership_duration*30),
            'photo': photo_filename,
            'gym_owner_id': ObjectId(current_user.id),
            'status': 'active',
            'needs_pt': needs_pt,
            'trainer_id': ObjectId(trainer_id) if trainer_id else None,
            'pt_sessions': pt_sessions,
            'health_info': {
                'weight': float(weight) if weight else None,
                'height': float(height) if height else None,
                'health_conditions': health_conditions
            },
            'emergency_contact': {
                'name': emergency_contact_name,
                'phone': emergency_contact_phone
            }
        }
        
        result = mongo.db.members.insert_one(member)
        
        # Create notification
        notification = {
            'message': f'New member {name} has been added',
            'created_at': datetime.utcnow(),
            'is_read': False,
            'gym_owner_id': ObjectId(current_user.id)
        }
        mongo.db.notifications.insert_one(notification)
        
        flash('Member added successfully!', 'success')
        return redirect(url_for('view_member', member_id=str(result.inserted_id)))
    
    return render_template('add_member.html', trainers=trainers)

@app.route('/member/<member_id>')
@login_required
def view_member(member_id):
    try:
        # Find member and their trainer if they have one
        member = mongo.db.members.find_one({
            '_id': ObjectId(member_id),
            'gym_owner_id': ObjectId(current_user.id)
        })
        
        if not member:
            flash('Member not found.', 'danger')
            return redirect(url_for('members'))
        
        # Convert ObjectId to string for template
        member['_id'] = str(member['_id'])
        
        # Get trainer information if assigned
        trainer = None
        if member.get('trainer_id'):
            trainer = mongo.db.trainers.find_one({'_id': ObjectId(member['trainer_id'])})
            if trainer:
                trainer['_id'] = str(trainer['_id'])
        
        # Calculate membership status
        now = datetime.utcnow()
        membership_end = member.get('membership_end')
        if isinstance(membership_end, str):
            try:
                membership_end = parse(membership_end)
            except:
                membership_end = None
        
        status = 'Expired'
        days_left = 0
        
        if membership_end:
            days_left = (membership_end - now).days
            if days_left > 7:
                status = 'Active'
            elif days_left > 0:
                status = 'Expiring Soon'
        
        # Ensure all dates are formatted consistently
        member['join_date'] = member.get('join_date', now)
        member['membership_start'] = member.get('membership_start', now)
        member['membership_end'] = membership_end or now
        
        return render_template('view_member.html', 
                             member=member, 
                             trainer=trainer,
                             status=status,
                             days_left=max(0, days_left))
                             
    except Exception as e:
        flash(f'Error viewing member details: {str(e)}', 'danger')
        return redirect(url_for('members'))

@app.route('/trainers')
@login_required
def trainers():
    trainers_list = list(mongo.db.trainers.find({
        'gym_owner_id': ObjectId(current_user.id)
    }))
    
    for trainer in trainers_list:
        trainer['_id'] = str(trainer['_id'])
        
    return render_template('trainers.html', trainers=trainers_list)

@app.route('/add_trainer', methods=['GET', 'POST'])
@login_required
def add_trainer():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        specialization = request.form.get('specialization')
        photo_data = request.form.get('photo')
        
        # Process photo if provided
        photo_filename = None
        if photo_data:
            photo_filename = save_photo(photo_data)
        
        trainer = {
            'name': name,
            'email': email,
            'phone': phone,
            'specialization': specialization,
            'photo': photo_filename,
            'gym_owner_id': ObjectId(current_user.id),
            'created_at': datetime.utcnow()
        }
        
        mongo.db.trainers.insert_one(trainer)
        flash('Trainer added successfully!', 'success')
        return redirect(url_for('trainers'))
        
    return render_template('add_trainer.html')

@app.route('/notifications')
@login_required
def notifications():
    notifications_list = list(mongo.db.notifications.find({
        'gym_owner_id': ObjectId(current_user.id)
    }).sort('created_at', -1))
    
    for notif in notifications_list:
        notif['_id'] = str(notif['_id'])
    
    return render_template('notifications.html', notifications=notifications_list)

@app.route('/mark_notification_read/<notification_id>')
@login_required
def mark_notification_read(notification_id):
    try:
        mongo.db.notifications.update_one(
            {
                '_id': ObjectId(notification_id),
                'gym_owner_id': ObjectId(current_user.id)
            },
            {'$set': {'is_read': True}}
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/notifications/unread/count')
@login_required
def get_unread_notification_count():
    count = mongo.db.notifications.count_documents({
        'gym_owner_id': ObjectId(current_user.id),
        'is_read': False
    })
    return jsonify({'count': count})

@app.route('/search')
@login_required
def search():
    search_query = request.args.get('query', '').strip()
    if not search_query:
        return jsonify([])
    
    results = []
    current_time = datetime.utcnow()
    
    try:
        # Search members
        members = mongo.db.members.find({
            'gym_owner_id': ObjectId(current_user.id),
            '$or': [
                {'name': {'$regex': search_query, '$options': 'i'}},
                {'email': {'$regex': search_query, '$options': 'i'}},
                {'phone': {'$regex': search_query, '$options': 'i'}}
            ]
        }).limit(5)

        for member in members:
            member_id = str(member['_id'])
            
            # Calculate membership status
            status = 'Expired'
            if 'membership_end' in member:
                membership_end = member['membership_end']
                if isinstance(membership_end, str):
                    try:
                        membership_end = datetime.strptime(membership_end, '%Y-%m-%d')
                    except ValueError:
                        membership_end = current_time
                status = 'Active' if membership_end > current_time else 'Expired'
            
            results.append({
                'id': member_id,
                'name': member.get('name', 'Unknown'),
                'email': member.get('email', 'N/A'),
                'phone': member.get('phone', 'N/A'),
                'type': 'Member',
                'status': status,
                'url': url_for('view_member', member_id=member_id)
            })

        # Search trainers
        trainers = mongo.db.trainers.find({
            'gym_owner_id': ObjectId(current_user.id),
            '$or': [
                {'name': {'$regex': search_query, '$options': 'i'}},
                {'email': {'$regex': search_query, '$options': 'i'}},
                {'phone': {'$regex': search_query, '$options': 'i'}},
                {'specialization': {'$regex': search_query, '$options': 'i'}}
            ]
        }).limit(5)

        for trainer in trainers:
            trainer_id = str(trainer['_id'])
            results.append({
                'id': trainer_id,
                'name': trainer.get('name', 'Unknown'),
                'email': trainer.get('email', 'N/A'),
                'phone': trainer.get('phone', 'N/A'),
                'type': 'Trainer',
                'specialization': trainer.get('specialization', 'N/A'),
                'url': url_for('update_trainer', trainer_id=trainer_id)
            })

        return jsonify(sorted(results, key=lambda x: x['name']))
        
    except Exception as e:
        print(f"Search error: {str(e)}")
        return jsonify({'error': 'An error occurred while searching'}), 500

@app.route('/members')
@login_required
def members():
    # Get current time for membership status
    now = datetime.utcnow()
    
    # Get all members and sort by name
    members_cursor = mongo.db.members.find({
        'gym_owner_id': ObjectId(current_user.id)
    }).sort('name', 1)
    
    # Convert cursor to list and process each member
    members_list = []
    for member in members_cursor:
        # Convert ObjectId to string for template
        member['_id'] = str(member['_id'])
        member['gym_owner_id'] = str(member['gym_owner_id'])
        
        # Format dates for template
        if 'join_date' in member:
            member['join_date'] = member['join_date']
        if 'membership_end' in member:
            member['membership_end'] = member['membership_end']
            # Add membership status
            member['status'] = 'active' if member['membership_end'] > now else 'expired'
            # Calculate days remaining
            days_remaining = (member['membership_end'] - now).days
            member['days_remaining'] = max(0, days_remaining)
            
        members_list.append(member)
    
    return render_template('members.html', members=members_list)

@app.route('/update_member/<member_id>', methods=['GET', 'POST'])
@login_required
def update_member(member_id):
    try:
        member = mongo.db.members.find_one({
            '_id': ObjectId(member_id),
            'gym_owner_id': ObjectId(current_user.id)
        })
        
        if not member:
            flash('Member not found', 'danger')
            return redirect(url_for('dashboard'))
        
        trainers = list(mongo.db.trainers.find({'gym_owner_id': ObjectId(current_user.id)}))
        for trainer in trainers:
            trainer['_id'] = str(trainer['_id'])
        
        if request.method == 'POST':
            # Basic validation
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            address = request.form.get('address', '').strip()
            
            if not all([name, email, phone, address]):
                flash('Please fill in all required fields', 'danger')
                return redirect(url_for('update_member', member_id=member_id))
            
            try:
                membership_duration = int(request.form.get('duration', 1))
                if membership_duration not in [1, 3, 6, 12]:
                    raise ValueError('Invalid membership duration')
            except ValueError:
                flash('Invalid membership duration', 'danger')
                return redirect(url_for('update_member', member_id=member_id))
            
            photo_data = request.form.get('photo')
            
            # PT Information with validation
            needs_pt = request.form.get('needs_pt') == 'on'
            trainer_id = request.form.get('trainer') if needs_pt else None
            try:
                pt_sessions = int(request.form.get('pt_sessions', 0)) if needs_pt else None
                if needs_pt and pt_sessions not in [1, 2, 3, 5]:
                    raise ValueError('Invalid PT sessions')
            except ValueError:
                flash('Invalid number of PT sessions', 'danger')
                return redirect(url_for('update_member', member_id=member_id))
            
            # Health Information with validation
            try:
                weight = float(request.form.get('weight')) if request.form.get('weight') else None
                height = float(request.form.get('height')) if request.form.get('height') else None
                if (weight and weight <= 0) or (height and height <= 0):
                    raise ValueError('Invalid weight or height')
            except ValueError:
                flash('Invalid weight or height values', 'danger')
                return redirect(url_for('update_member', member_id=member_id))
            
            health_conditions = request.form.get('health_conditions', '').strip()
            
            # Emergency Contact validation
            emergency_contact_name = request.form.get('emergency_contact_name', '').strip()
            emergency_contact_phone = request.form.get('emergency_contact_phone', '').strip()
            
            if not emergency_contact_name or not emergency_contact_phone:
                flash('Emergency contact information is required', 'danger')
                return redirect(url_for('update_member', member_id=member_id))
            
            # Check if email changed and new email exists
            if email != member['email']:
                existing_member = mongo.db.members.find_one({
                    'gym_owner_id': ObjectId(current_user.id),
                    'email': email,
                    '_id': {'$ne': ObjectId(member_id)}
                })
                if existing_member:
                    flash('A member with this email already exists', 'danger')
                    return redirect(url_for('update_member', member_id=member_id))
            
            # Process photo if provided
            photo_filename = member.get('photo')
            if photo_data and photo_data.startswith('data:image'):
                try:
                    photo_filename = save_photo(photo_data)
                    
                    # Delete old photo if it exists
                    if member.get('photo'):
                        old_photo_path = os.path.join(app.config['UPLOAD_FOLDER'], member['photo'].split('/')[-1])
                        if os.path.exists(old_photo_path):
                            os.remove(old_photo_path)
                except Exception as e:
                    flash('Error processing photo: ' + str(e), 'danger')
                    return redirect(url_for('update_member', member_id=member_id))
            
            # Calculate new membership end date
            current_end = member.get('membership_end', datetime.utcnow())
            if current_end < datetime.utcnow():
                # If membership has expired, start from now
                new_end = datetime.utcnow() + timedelta(days=membership_duration*30)
            else:
                # If membership is still active, extend from current end date
                new_end = current_end + timedelta(days=membership_duration*30)
            
            # Update member in database
            update_data = {
                'name': name,
                'email': email,
                'phone': phone,
                'address': address,
                'membership_end': new_end,
                'photo': photo_filename,
                'needs_pt': needs_pt,
                'trainer_id': ObjectId(trainer_id) if trainer_id else None,
                'pt_sessions': pt_sessions,
                'health_info': {
                    'weight': weight,
                    'height': height,
                    'health_conditions': health_conditions
                },
                'emergency_contact': {
                    'name': emergency_contact_name,
                    'phone': emergency_contact_phone
                },
                'updated_at': datetime.utcnow()
            }
            
            mongo.db.members.update_one(
                {'_id': ObjectId(member_id)},
                {'$set': update_data}
            )
            
            flash('Member updated successfully!', 'success')
            return redirect(url_for('view_member', member_id=member_id))
        
        return render_template('update_member.html', member=member, trainers=trainers)
        
    except Exception as e:
        flash('An error occurred: ' + str(e), 'danger')
        return redirect(url_for('members'))

@app.route('/update_trainer/<trainer_id>', methods=['GET', 'POST'])
@login_required
def update_trainer(trainer_id):
    trainer = mongo.db.trainers.find_one({
        '_id': ObjectId(trainer_id),
        'gym_owner_id': ObjectId(current_user.id)
    })
    
    if not trainer:
        flash('Trainer not found', 'danger')
        return redirect(url_for('trainers'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        specialization = request.form.get('specialization')
        
        # Check if email changed and new email exists
        if email != trainer['email']:
            existing_trainer = mongo.db.trainers.find_one({
                'gym_owner_id': ObjectId(current_user.id),
                'email': email,
                '_id': {'$ne': ObjectId(trainer_id)}
            })
            if existing_trainer:
                flash('A trainer with this email already exists', 'danger')
                return redirect(url_for('update_trainer', trainer_id=trainer_id))
        
        # Update trainer in database
        mongo.db.trainers.update_one(
            {'_id': ObjectId(trainer_id)},
            {'$set': {
                'name': name,
                'email': email,
                'phone': phone,
                'specialization': specialization
            }}
        )
        
        flash('Trainer updated successfully!', 'success')
        return redirect(url_for('trainers'))
    
    return render_template('update_trainer.html', trainer=trainer)

@app.route('/delete_member/<member_id>', methods=['GET'])
@login_required
def delete_member(member_id):
    try:
        result = mongo.db.members.delete_one({
            '_id': ObjectId(member_id),
            'gym_owner_id': ObjectId(current_user.id)
        })
        if result.deleted_count == 1:
            flash('Member deleted successfully!', 'success')
        else:
            flash('Member not found or you do not have permission to delete this member.', 'danger')
    except Exception as e:
        flash(f'Error deleting member: {str(e)}', 'danger')
    return redirect(url_for('members'))

@app.route('/delete_trainer/<trainer_id>', methods=['POST'])
@login_required
def delete_trainer(trainer_id):
    try:
        result = mongo.db.trainers.delete_one({
            '_id': ObjectId(trainer_id),
            'gym_owner_id': ObjectId(current_user.id)
        })
        if result.deleted_count == 1:
            flash('Trainer deleted successfully!', 'success')
        else:
            flash('Trainer not found or you do not have permission to delete this trainer.', 'danger')
    except Exception as e:
        flash(f'Error deleting trainer: {str(e)}', 'danger')
    return redirect(url_for('trainers'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        gym_name = request.form.get('gym_name')
        email = request.form.get('email')
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        photo_data = request.form.get('photo')
        subscription_plan = request.form.get('subscription_plan')
        
        user_id = current_user.user_data['_id']
        update_data = {}
        
        # Update basic info
        if gym_name and email:
            update_data.update({
                'gym_name': gym_name,
                'email': email
            })
        
        # Update photo if provided
        if photo_data and photo_data.startswith('data:image'):
            photo_url = save_photo(photo_data)
            if photo_url:
                update_data['photo'] = photo_url
        
        # Update password if provided
        if current_password and new_password:
            if check_password_hash(current_user.user_data['password'], current_password):
                update_data['password'] = generate_password_hash(new_password)
            else:
                flash('Current password is incorrect', 'danger')
                return redirect(url_for('settings'))
        
        # Update subscription plan
        if subscription_plan:
            update_data['subscription_plan'] = subscription_plan
        
        if update_data:
            mongo.db.gym_owners.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': update_data}
            )
            flash('Settings updated successfully!', 'success')
        
        return redirect(url_for('settings'))
    
    return render_template('settings.html')

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_data = mongo.db.gym_owners.find_one({'_id': ObjectId(current_user.id)})
    now = datetime.utcnow()
    subscription_end = user_data.get('subscription_end', None)
    days_remaining = (subscription_end - now).days if subscription_end else None

    return render_template(
        'profile.html',
        user={
            'name': user_data.get('name', 'User'),
            'email': user_data.get('email', ''),
            'photo': user_data.get('photo', None),
            'subscription_end': subscription_end,
        },
        now=now
    )

@app.route('/privacy_policy')
def privacy_policy():
    return render_template('privacy_policy.html')

@app.route('/terms_conditions')
def terms_conditions():
    return render_template('terms_conditions.html')

@app.route('/refund_cancellation_policy')
def refund_cancellation_policy():
    return render_template('refund_cancellation_policy.html')

@app.route('/support')
def support():
    return render_template('support.html')

@app.template_filter('format_date')
def format_date(date):
    if isinstance(date, str):
        date = parse(date)
    india_tz = pytz.timezone('Asia/Kolkata')  # Define the Indian time zone
    date = date.astimezone(india_tz)  # Convert the date to the Indian time zone
    return date.strftime('%Y-%m-%d %H:%M')

@app.route('/select_subscription', methods=['GET', 'POST'])
@login_required
def select_subscription():
    if request.method == 'POST':
        subscription_plan = request.form.get('subscription_plan')
        if subscription_plan not in ['Basic', 'Standard', 'Premium']:
            flash('Invalid subscription plan selected', 'danger')
            return redirect(url_for('select_subscription'))
        
        mongo.db.gym_owners.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {'subscription_plan': subscription_plan}}
        )
        
        flash('Subscription plan updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('select_subscription.html')

@app.route('/trainer/<trainer_id>')
@login_required
def view_trainer(trainer_id):
    try:
        trainer = mongo.db.trainers.find_one({
            '_id': ObjectId(trainer_id),
            'gym_owner_id': ObjectId(current_user.id)
        })
        
        if not trainer:
            flash('Trainer not found.', 'danger')
            return redirect(url_for('trainers'))
        
        # Convert ObjectId to string for template
        trainer['_id'] = str(trainer['_id'])
        
        return render_template('view_trainer.html', trainer=trainer)
                             
    except Exception as e:
        flash(f'Error viewing trainer details: {str(e)}', 'danger')
        return redirect(url_for('trainers'))

@app.route('/admin/members')
@login_required
def admin_members():
    members = list(mongo.db.members.find({'gym_owner_id': ObjectId(current_user.id)}))
    return render_template('admin/members.html', members=members)

@app.route('/admin/trainers')
@login_required
def admin_trainers():
    trainers = list(mongo.db.trainers.find({'gym_owner_id': ObjectId(current_user.id)}))
    return render_template('admin/trainers.html', trainers=trainers)

@app.route('/admin/classes')
@login_required
def admin_classes():
    classes = list(mongo.db.classes.find({'gym_owner_id': ObjectId(current_user.id)}))
    return render_template('admin/classes.html', classes=classes)

@app.route('/admin/payments')
@login_required
def admin_payments():
    payments = list(mongo.db.payments.find({'gym_owner_id': ObjectId(current_user.id)}))
    return render_template('admin/payments.html', payments=payments)

@app.route('/admin/attendance')
@login_required
def admin_attendance():
    attendance_records = list(mongo.db.attendance.find({'gym_owner_id': ObjectId(current_user.id)}))
    return render_template('admin/attendance.html', attendance_records=attendance_records)

@app.route('/admin/inventory')
@login_required
def admin_inventory():
    equipment = list(mongo.db.equipment.find({'gym_owner_id': ObjectId(current_user.id)}))
    return render_template('admin/inventory.html', equipment=equipment)

@app.route('/member/profile')
@login_required
def member_profile():
    return render_template('member/profile.html', user=current_user.user_data)

@app.route('/member/classes')
@login_required
def member_classes():
    classes = list(mongo.db.classes.find({'gym_owner_id': ObjectId(current_user.id)}))
    return render_template('member/classes.html', classes=classes)

@app.route('/member/workout')
@login_required
def member_workout():
    workout_plans = list(mongo.db.workout_plans.find({'member_id': ObjectId(current_user.id)}))
    return render_template('member/workout.html', workout_plans=workout_plans)

@app.route('/member/feedback')
@login_required
def member_feedback():
    return render_template('member/feedback.html')

@app.route('/member/progress')
@login_required
def member_progress():
    progress_reports = list(mongo.db.progress_reports.find({'member_id': ObjectId(current_user.id)}))
    return render_template('member/progress.html', progress_reports=progress_reports)

@app.route('/trainer/clients')
@login_required
def trainer_clients():
    clients = list(mongo.db.members.find({'trainer_id': ObjectId(current_user.id)}))
    return render_template('trainer/clients.html', clients=clients)

@app.route('/trainer/classes')
@login_required
def trainer_classes():
    classes = list(mongo.db.classes.find({'trainer_id': ObjectId(current_user.id)}))
    return render_template('trainer/classes.html', classes=classes)

@app.route('/trainer/performance')
@login_required
def trainer_performance():
    performance_reports = list(mongo.db.performance_reports.find({'trainer_id': ObjectId(current_user.id)}))
    return render_template('trainer/performance.html', performance_reports=performance_reports)

@app.route('/analytics/revenue')
@login_required
def analytics_revenue():
    revenue_reports = list(mongo.db.revenue_reports.find({'gym_owner_id': ObjectId(current_user.id)}))
    return render_template('analytics/revenue.html', revenue_reports=revenue_reports)

@app.route('/analytics/attendance')
@login_required
def analytics_attendance():
    attendance_reports = list(mongo.db.attendance_reports.find({'gym_owner_id': ObjectId(current_user.id)}))
    return render_template('analytics/attendance.html', attendance_reports=attendance_reports)

@app.route('/analytics/performance')
@login_required
def analytics_performance():
    performance_reports = list(mongo.db.performance_reports.find({'gym_owner_id': ObjectId(current_user.id)}))
    return render_template('analytics/performance.html', performance_reports=performance_reports)

@app.route('/test_email')
def test_email():
    try:
        msg = Message(
            'Test Email',
            sender=app.config['MAIL_USERNAME'],
            recipients=['recipient-email@example.com']  # Replace with a test recipient email
        )
        msg.body = 'This is a test email sent from Flask-Mail.'
        mail.send(msg)
        return 'Test email sent successfully!'
    except Exception as e:
        return f'Error sending test email: {str(e)}'

@app.route('/user_panel')
@login_required
def user_panel():
    # Ensure the user is a normal user
    if current_user.user_data.get('role', 'normal') != 'normal':
        flash('Access denied. This panel is for normal users only.', 'danger')
        return redirect(url_for('dashboard'))
    
    # Fetch blogs, articles, diet charts, workout videos, and workout tracking data
    blogs = list(mongo.db.blogs.find().sort('created_at', -1))
    articles = list(mongo.db.articles.find().sort('created_at', -1))
    diet_charts = list(mongo.db.diet_charts.find({'user_id': ObjectId(current_user.id)}))
    workout_videos = list(mongo.db.workout_videos.find().sort('created_at', -1))
    workout_tracking = list(mongo.db.workout_tracking.find({'user_id': ObjectId(current_user.id)}))
    
    # Convert ObjectId to string for template compatibility
    for blog in blogs:
        blog['_id'] = str(blog['_id'])
    for article in articles:
        article['_id'] = str(article['_id'])
    for chart in diet_charts:
        chart['_id'] = str(chart['_id'])
    for tracking in workout_tracking:
        tracking['_id'] = str(tracking['_id'])
    
    return render_template(
        'user_panel.html',
        blogs=blogs,
        articles=articles,
        diet_charts=diet_charts,
        workout_videos=workout_videos,
        workout_tracking=workout_tracking
    )

@app.before_request
def restrict_access():
    # Restrict normal users and gym owners from accessing developer features
    restricted_routes_for_non_developers = ['developer_panel']
    # Restrict normal users from accessing gym management features
    restricted_routes_for_normal_users = [
        'dashboard', 'members', 'trainers', 'add_member', 'add_trainer',
        'update_member', 'update_trainer', 'delete_member', 'delete_trainer',
        'admin_members', 'admin_trainers', 'admin_classes', 'admin_payments',
        'admin_attendance', 'admin_inventory'
    ]
    # Restrict gym owners from accessing normal user features
    restricted_routes_for_gym_owners = [
        'user_panel', 'view_blog', 'view_article', 'view_diet_chart'
    ]

    if current_user.is_authenticated:
        user_role = current_user.user_data.get('role')
        if user_role != 'developer' and request.endpoint in restricted_routes_for_non_developers:
            flash('Access denied. This panel is for developers only.', 'danger')
            return redirect(url_for('index'))
        if user_role == 'normal' and request.endpoint in restricted_routes_for_normal_users:
            flash('Access denied. This feature is for gym owners only.', 'danger')
            return redirect(url_for('user_panel'))
        elif user_role == 'gym_owner' and request.endpoint in restricted_routes_for_gym_owners:
            flash('Access denied. This feature is for normal users only.', 'danger')
            return redirect(url_for('dashboard'))

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_panel():
    # Ensure the user is a developer
    if current_user.user_data.get('role') != 'developer':
        flash('Access denied. This panel is for developers only.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Handle content creation (e.g., blog, article)
        content_type = request.form.get('content_type')
        title = request.form.get('title')
        content = request.form.get('content')
        if content_type and title and content:
            collection_map = {
                'blog': 'blogs',
                'article': 'articles'
            }
            collection = collection_map.get(content_type)
            if collection:
                mongo.db[collection].insert_one({
                    'title': title,
                    'content': content,
                    'created_at': datetime.utcnow(),
                    'admin_id': ObjectId(current_user.id)
                })
                flash(f'{content_type.capitalize()} posted successfully!', 'success')
            else:
                flash('Invalid content type.', 'danger')
        else:
            flash('All fields are required.', 'danger')

    return render_template('admin_panel.html')

@app.route('/view_blog/<blog_id>')
@login_required
def view_blog(blog_id):
    if blog_id == 'latest':
        # Fetch the most recent blog
        blog = mongo.db.blogs.find_one(sort=[('created_at', -1)])
    else:
        try:
            blog = mongo.db.blogs.find_one({'_id': ObjectId(blog_id)})
        except bson.errors.InvalidId:
            flash('Invalid blog ID.', 'danger')
            return redirect(url_for('user_panel'))
    
    if not blog:
        flash('Blog not found.', 'danger')
        return redirect(url_for('user_panel'))
    
    return render_template('view_blog.html', blog=blog)

@app.route('/view_article/<article_id>')
@login_required
def view_article(article_id):
    if article_id == 'latest':
        # Fetch the most recent article
        article = mongo.db.articles.find_one(sort=[('created_at', -1)])
    else:
        try:
            article = mongo.db.articles.find_one({'_id': ObjectId(article_id)})
        except bson.errors.InvalidId:
            flash('Invalid article ID.', 'danger')
            return redirect(url_for('user_panel'))
    
    if not article:
        flash('Article not found.', 'danger')
        return redirect(url_for('user_panel'))
    
    return render_template('view_article.html', article=article)

@app.route('/view_diet_chart/<chart_id>')
@login_required
def view_diet_chart(chart_id):
    chart = mongo.db.diet_charts.find_one({'_id': ObjectId(chart_id)})
    if not chart:
        flash('Diet chart not found.', 'danger')
        return redirect(url_for('user_panel'))
    return render_template('view_diet_chart.html', chart=chart)

@app.route('/developer_panel', methods=['GET', 'POST'])
@login_required
def developer_panel():
    # Ensure the user is a developer
    if current_user.user_data.get('role') != 'developer':
        flash('Access denied. This panel is for developers only.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Handle developer-specific actions (e.g., managing users, content, etc.)
        action = request.form.get('action')
        if action == 'reset_password':
            user_email = request.form.get('email')
            new_password = request.form.get('new_password')
            if user_email and new_password:
                hashed_password = generate_password_hash(new_password)
                mongo.db.gym_owners.update_one(
                    {'email': user_email},
                    {'$set': {'password': hashed_password}}
                )
                flash('Password reset successfully!', 'success')
            else:
                flash('Email and new password are required.', 'danger')

    return render_template('developer_panel.html')

if __name__ == '__main__':
    app.run(debug=True, port=7001, host='0.0.0.0')
