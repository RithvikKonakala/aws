from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import boto3
from boto3.dynamodb.conditions import Key, Attr
import uuid
import json

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Initialize DynamoDB resource
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')  # Update to your AWS region
sns = boto3.client('sns', region_name='ap-south-1')

# DynamoDB Tables
users_table = dynamodb.Table('Users')  # Ensure the 'Users' table is created in DynamoDB
bookings_table = dynamodb.Table('Bookings')  # Ensure the 'Bookings' table is created in DynamoDB

# Global constant for car type prices per day
PRICE_PER_DAY = {
    'sedan': 2500,
    'mini campervan': 6000,
    'suv': 4000
}

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
            # Check if user already exists
            response = users_table.query(
                KeyConditionExpression=Key('email').eq(email)
            )
            
            if response['Items']:
                flash("Email already registered. Please login.", "danger")
                return redirect(url_for('login'))
            
            # Create new user
            user_id = str(uuid.uuid4())
            users_table.put_item(
                Item={
                    'id': user_id,
                    'name': name,
                    'email': email,
                    'password': password,  # Note: In production, passwords should be hashed
                    'mobile_number': mobile_number,
                    'created_at': datetime.now().isoformat()
                }
            )
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
            # Query for user with email
            response = users_table.scan(
                FilterExpression=Attr('email').eq(email) & Attr('password').eq(password)
            )
            
            if response['Items']:
                user = response['Items'][0]
                session['user_id'] = user['id']
                session['username'] = user['name']
                flash("Login successful!", "success")
                return redirect(url_for('car_type'))
            else:
                flash("Invalid login. Please try again.", "danger")
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
            
            # Insert booking into DynamoDB
            bookings_table.put_item(
                Item={
                    'booking_id': booking_id,
                    'user_id': user_id,
                    'car_type': car_type,
                    'num_days': num_days,
                    'pickup': check_in,
                    'dropoff': check_out,
                    'special_requests': special_requests,
                    'payment_mode': payment_mode,
                    'total_price': total_price,
                    'status': 'confirmed',
                    'created_at': datetime.now().isoformat()
                }
            )
            
            # Optional: Send confirmation notification via SNS
            try:
                # Get user details to include in notification
                user_response = users_table.get_item(
                    Key={'id': user_id}
                )
                
                if 'Item' in user_response:
                    user = user_response['Item']
                    # Create the message for SNS
                    message = f"Booking Confirmation\n\nDear {user['name']},\n\nYour booking for a {car_type} for {num_days} days has been confirmed.\nPickup: {check_in}\nDropoff: {check_out}\nTotal Price: ₹{total_price}\n\nThank you for your business!"
                    
                    # Create an SNS topic if you want to use it
                    # topic = sns.create_topic(Name='BookingConfirmations')
                    # topic_arn = topic['TopicArn']
                    
                    # For direct SMS (if configured and allowed in your region)
                    # sns.publish(
                    #     PhoneNumber=user['mobile_number'],
                    #     Message=message
                    # )
            except Exception as e:
                print(f"Notification error: {e}")
                # Continue with the booking process even if notification fails

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
        # Query all bookings for the user from DynamoDB
        response = bookings_table.scan(
            FilterExpression=Attr('user_id').eq(user_id)
        )
        
        bookings = response['Items']
        
        # Sort bookings by creation date (newest first)
        bookings.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return render_template('my_bookings.html', bookings=bookings)
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
        # Get the booking to verify it belongs to the user
        response = bookings_table.get_item(
            Key={'booking_id': booking_id}
        )
        
        if 'Item' not in response or response['Item']['user_id'] != user_id:
            flash("Unauthorized or booking not found.", "danger")
            return redirect(url_for('my_bookings'))
        
        # Update the booking status to cancelled
        bookings_table.update_item(
            Key={'booking_id': booking_id},
            UpdateExpression="set #status = :s, cancelled_at = :c",
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':s': 'cancelled',
                ':c': datetime.now().isoformat()
            }
        )
        
        flash("Booking cancelled successfully.", "success")
    except Exception as e:
        flash(f"Error cancelling booking: {str(e)}", "danger")
    
    return redirect(url_for('my_bookings'))

if __name__ == '__main__':
    app.run(debug=True)