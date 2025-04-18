from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import uuid
import os
import boto3
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal
import json

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Initialize DynamoDB client without credentials
# When running on EC2 with an IAM role, boto3 will automatically use the instance profile credentials
dynamodb = boto3.resource('dynamodb')

# Global constant for car type prices per day
PRICE_PER_DAY = {
    'sedan': 2500,
    'mini campervan': 6000,
    'suv': 4000
}

def init_db():
    """Initialize DynamoDB tables if they don't exist"""
    tables = list(dynamodb.tables.all())
    table_names = [table.name for table in tables]
    
    # Create Users table if it doesn't exist
    if 'users' not in table_names:
        users_table = dynamodb.create_table(
            TableName='users',
            KeySchema=[
                {'AttributeName': 'id', 'KeyType': 'HASH'}  # Partition key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'id', 'AttributeType': 'S'},
                {'AttributeName': 'email', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'EmailIndex',
                    'KeySchema': [
                        {'AttributeName': 'email', 'KeyType': 'HASH'},
                    ],
                    'Projection': {
                        'ProjectionType': 'ALL'
                    },
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            ProvisionedThroughput={'ReadCapacityUnits': 5, 'WriteCapacityUnits': 5}
        )
        # Wait until the table exists
        users_table.meta.client.get_waiter('table_exists').wait(TableName='users')
        print("users table created successfully!")
    
    # Create Bookings table if it doesn't exist
    if 'Bookings' not in table_names:
        bookings_table = dynamodb.create_table(
            TableName='Bookings',
            KeySchema=[
                {'AttributeName': 'booking_id', 'KeyType': 'HASH'}  # Partition key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'booking_id', 'AttributeType': 'S'},
                {'AttributeName': 'user_id', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'UserIdIndex',
                    'KeySchema': [
                        {'AttributeName': 'user_id', 'KeyType': 'HASH'},
                    ],
                    'Projection': {
                        'ProjectionType': 'ALL'
                    },
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            ProvisionedThroughput={'ReadCapacityUnits': 5, 'WriteCapacityUnits': 5}
        )
        # Wait until the table exists
        bookings_table.meta.client.get_waiter('table_exists').wait(TableName='Bookings')
        print("Bookings table created successfully!")

# Initialize database when app starts
try:
    init_db()
except Exception as e:
    print(f"Error initializing database: {str(e)}")

# Helper class to convert DynamoDB items to JSON serializable format
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super(DecimalEncoder, self).default(o)

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
            # Get the Users table
            users_table = dynamodb.Table('Users')
            
            # Check if user already exists
            response = users_table.query(
                IndexName='EmailIndex',
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
                    'password': password,  # In production, use proper password hashing
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
            # Get the Users table
            users_table = dynamodb.Table('Users')
            
            # Query for user with email
            response = users_table.query(
                IndexName='EmailIndex',
                KeyConditionExpression=Key('email').eq(email)
            )
            
            if response['Items'] and response['Items'][0]['password'] == password:
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
            
            # Get the Bookings table
            bookings_table = dynamodb.Table('Bookings')
            
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
                    'total_price': Decimal(str(total_price)),  # Convert to Decimal for DynamoDB
                    'status': 'confirmed',
                    'created_at': datetime.now().isoformat()
                }
            )
            
            # Get user details for confirmation message
            users_table = dynamodb.Table('Users')
            user_response = users_table.get_item(Key={'id': user_id})
            
            if 'Item' in user_response:
                user = user_response['Item']
                # Here you would implement any notification logic
                # In a real app, you might use an email service or SMS gateway
                print(f"Booking Confirmation for {user['name']}: {car_type} for {num_days} days")
            
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
        # Get the Bookings table
        bookings_table = dynamodb.Table('Bookings')
        
        # Query all bookings for the user from DynamoDB
        response = bookings_table.query(
            IndexName='UserIdIndex',
            KeyConditionExpression=Key('user_id').eq(user_id)
        )
        
        # Convert Decimal types to float for JSON serialization
        bookings_list = json.loads(json.dumps(response['Items'], cls=DecimalEncoder))
        
        # Sort by created_at in descending order
        bookings_list = sorted(bookings_list, key=lambda x: x.get('created_at', ''), reverse=True)
        
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
        # Get the Bookings table
        bookings_table = dynamodb.Table('Bookings')
        
        # Get the booking to verify it belongs to the user
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        
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

# Add a logout route
@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)
