from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import uuid
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Database setup
DATABASE_PATH = 'car_rental.db'

# Global constant for car type prices per day
PRICE_PER_DAY = {
    'sedan': 2500,
    'mini campervan': 6000,
    'suv': 4000
}

def init_db():
    """Initialize database if it doesn't exist"""
    # Check if database file exists
    if not os.path.exists(DATABASE_PATH):
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Create Users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            mobile_number TEXT,
            created_at TEXT
        )
        ''')
        
        # Create Bookings table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            car_type TEXT NOT NULL,
            num_days INTEGER NOT NULL,
            pickup TEXT NOT NULL,
            dropoff TEXT NOT NULL,
            special_requests TEXT,
            payment_mode TEXT NOT NULL,
            total_price REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT,
            cancelled_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
        
        conn.commit()
        conn.close()

def get_db_connection():
    """Create a connection to the SQLite database"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # This enables column access by name
    return conn

# Initialize database when app starts
init_db()

# Home Route
@app.route('/')
def home():
    return render_template('home.html')

# Register Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        mobile_number = request.form['mobile_number']
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if user already exists
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()
            
            if user:
                flash("Email already registered. Please login.", "danger")
                conn.close()
                return redirect(url_for('login'))
            
            # Create new user
            user_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO users (id, name, email, password, mobile_number, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, name, email, password, mobile_number, datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
            
            flash("Thanks for registering!", "success")
            return redirect(url_for('login'))
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")
    
    return render_template('register.html')

# Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Query for user with email and password
            cursor.execute("SELECT * FROM users WHERE email = ? AND password = ?", (email, password))
            user = cursor.fetchone()
            
            if user:
                session['user_id'] = user['id']
                session['username'] = user['name']
                flash("Login successful!", "success")
                conn.close()
                return redirect(url_for('car_type'))
            else:
                flash("Invalid login. Please try again.", "danger")
                conn.close()
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")
    
    return render_template('login.html')

# Check Car types
@app.route('/car_type', methods=['GET', 'POST'])
def car_type():
    if request.method == 'POST':
        car_type = request.form['car_type']  # Retrieve the car type from the form
        return redirect(url_for('book', car_type=car_type))  # Pass car_type

    return render_template('car_type.html')

@app.route('/book/<car_type>', methods=['GET', 'POST'])
def book(car_type):
    if 'user_id' not in session:
        flash("Please login first to book a car", "danger")
        return redirect(url_for('login'))
        
    if request.method == 'GET':
        # Pass the correct price based on the car type to the HTML
        return render_template('booking.html', car_type=car_type, price_per_day=PRICE_PER_DAY.get(car_type.lower(), 0))

    if request.method == 'POST':
        try:
            # Retrieve form inputs
            check_in = request.form['check_in']
            check_out = request.form['check_out']
            special_requests = request.form['special_requests']
            payment_mode = request.form['payment_mode']

            # Get user ID from session
            user_id = session.get('user_id')

            # Calculate the number of days
            check_in_date = datetime.strptime(check_in, "%Y-%m-%d")
            check_out_date = datetime.strptime(check_out, "%Y-%m-%d")
            num_days = (check_out_date - check_in_date).days

            # Get the daily rate based on the car type
            daily_rate = PRICE_PER_DAY.get(car_type.lower(), 0)
            total_price = daily_rate * num_days

            # Create unique booking ID
            booking_id = str(uuid.uuid4())
            
            # Insert booking into SQLite
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO bookings 
                (booking_id, user_id, car_type, num_days, pickup, dropoff, special_requests, 
                payment_mode, total_price, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    booking_id, user_id, car_type, num_days, check_in, check_out, 
                    special_requests, payment_mode, total_price, 'confirmed', 
                    datetime.now().isoformat()
                )
            )
            conn.commit()
            
            # Get user details for confirmation message
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            
            if user:
                # Here you would implement any notification logic
                # In a real app, you might use an email service or SMS gateway instead of SNS
                print(f"Booking Confirmation for {user['name']}: {car_type} for {num_days} days")
            
            conn.close()
            return redirect(url_for('thank_you'))

        except Exception as e:
            flash(f"Error creating booking: {str(e)}", "danger")
            return redirect(url_for('car_type'))

# Thank You Route
@app.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')

# My Bookings Route
@app.route('/my_bookings')
def my_bookings():
    user_id = session.get('user_id')
    if not user_id:
        flash("You need to log in to view your bookings.", "danger")
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query all bookings for the user from SQLite
        cursor.execute("SELECT * FROM bookings WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        bookings = cursor.fetchall()
        
        # Convert to list of dictionaries for template compatibility
        bookings_list = []
        for booking in bookings:
            booking_dict = dict(booking)
            bookings_list.append(booking_dict)
        
        conn.close()
        return render_template('my_bookings.html', bookings=bookings_list)
    except Exception as e:
        flash(f"Error retrieving bookings: {str(e)}", "danger")
        return render_template('my_bookings.html', bookings=[])

# Add a route to cancel booking
@app.route('/cancel_booking/<booking_id>', methods=['POST'])
def cancel_booking(booking_id):
    user_id = session.get('user_id')
    if not user_id:
        flash("You need to log in to cancel bookings.", "danger")
        return redirect(url_for('login'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get the booking to verify it belongs to the user
        cursor.execute("SELECT * FROM bookings WHERE booking_id = ?", (booking_id,))
        booking = cursor.fetchone()
        
        if not booking or booking['user_id'] != user_id:
            flash("Unauthorized or booking not found.", "danger")
            conn.close()
            return redirect(url_for('my_bookings'))
        
        # Update the booking status to cancelled
        cursor.execute(
            "UPDATE bookings SET status = ?, cancelled_at = ? WHERE booking_id = ?",
            ('cancelled', datetime.now().isoformat(), booking_id)
        )
        conn.commit()
        conn.close()
        
        flash("Booking cancelled successfully.", "success")
    except Exception as e:
        flash(f"Error cancelling booking: {str(e)}", "danger")
    
    return redirect(url_for('my_bookings'))

# Add a logout route
@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)