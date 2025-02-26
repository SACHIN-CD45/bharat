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

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'  # Change this to a secure secret key
app.config['MONGO_URI'] = 'mongodb://localhost:27017/gym_management'
app.config['UPLOAD_FOLDER'] = os.path.join(app.static_folder, 'uploads')

# Initialize MongoDB
mongo = PyMongo(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

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
        return redirect(url_for('dashboard'))
    return render_template('index.html')

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
    
    return render_template('dashboard.html',
                         active_members=active_members,
                         expired_members=expired_members,
                         expiring_soon=expiring_soon,
                         members=recent_members,
                         notifications=notifications,
                         now=now)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        gym_name = request.form.get('gym_name')
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        photo_data = request.form.get('photo')
        
        if mongo.db.gym_owners.find_one({'email': email}):
            flash('Email already registered', 'danger')
            return redirect(url_for('signup'))
        
        # Save photo if provided
        photo_url = None
        if photo_data:
            photo_url = save_photo(photo_data)
        
        # Hash password
        hashed_password = generate_password_hash(password)
        
        # Create user with all required fields
        user_data = {
            'gym_name': gym_name,
            'email': email,
            'password': hashed_password,
            'name': name or gym_name,  # Use gym name as fallback
            'photo': photo_url,
            'created_at': datetime.utcnow()
        }
        
        result = mongo.db.gym_owners.insert_one(user_data)
        user_data['_id'] = result.inserted_id
        
        # Log in the new user
        user = User(user_data)
        login_user(user)
        
        flash('Account created successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user_data = mongo.db.gym_owners.find_one({'email': email})
        
        if user_data and check_password_hash(user_data['password'], password):
            # Ensure all required fields exist
            if 'name' not in user_data:
                user_data['name'] = user_data.get('gym_name', 'User')
            if 'photo' not in user_data:
                user_data['photo'] = None
            
            user = User(user_data)
            login_user(user)
            
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        
        flash('Invalid email or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

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
        
        trainer = {
            'name': name,
            'email': email,
            'phone': phone,
            'specialization': specialization,
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

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        gym_name = request.form.get('gym_name')
        email = request.form.get('email')
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        photo_data = request.form.get('photo')
        
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
                flash('Password updated successfully!', 'success')
            else:
                flash('Current password is incorrect!', 'danger')
                return redirect(url_for('settings'))
        
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
    if request.method == 'POST':
        name = request.form.get('name')
        photo_data = request.form.get('photo')
        
        user_id = current_user.user_data['_id']
        update_data = {}
        
        # Update name if provided
        if name:
            update_data['name'] = name
        
        # Update photo if provided
        if photo_data and photo_data.startswith('data:image'):
            photo_url = save_photo(photo_data)
            if photo_url:
                update_data['photo'] = photo_url
        
        if update_data:
            mongo.db.gym_owners.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': update_data}
            )
            flash('Profile updated successfully!', 'success')
        
        return redirect(url_for('profile'))
    
    return render_template('profile.html')

@app.template_filter('format_date')
def format_date(date):
    if isinstance(date, str):
        date = parse(date)
    return date.strftime('%Y-%m-%d %H:%M')



if __name__ == '__main__':
    app.run(debug=True, port=7002, host='0.0.0.0')
