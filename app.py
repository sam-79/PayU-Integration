
from genericpath import isfile
from flask import Flask, render_template, request, jsonify

# import requests
import hashlib
import string
import random
from decouple import config
import os
import sqlite3 as sql

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

app = Flask(__name__)
app.debug = True

# #credentials
merchant_key = os.getenv('key', config('key'))
merchant_salt_v1 = os.getenv('salt', config('salt'))
gmail_user = os.getenv('gmail_user', config('gmail_user'))
gmail_pass = os.getenv('gmail_pass', config('gmail_pass'))



# database connection
if(not os.path.isfile('database/transactions.db')):
    conn = sql.connect('database/transactions.db')
    conn.execute(
        """create table transactions_details (
            txnid varchar[25] primary key,
            amount int,
            firstname varchar[30],
            email varchar[30],
            status varchar[10],
            txn_ref_id varchar[100]
        );"""
    )
    conn.close()


@app.route('/')
def donate_page():
    return render_template('donate.html')


@app.route('/infoForm.html')
def get_details():
    
    return render_template('infoForm.html')


@app.route('/initiate', methods=['POST'])
def initiate():

    # json data from user details request
    data = request.json

    # donation amount
    try:
        amount = str(int(data['amount']))
    except:
        amount = str("{0:.2f}".format(float(data['amount'])))

    # product info
    productinfo = 'donation'

    # Payer Name
    firstname = data['firstname']
    lastname = data['lastname']

    # Payer email
    email = data['email']

    # Payer Mob
    phone = data['phone']

    # Payer Address
    address1 = data['address1']
    city = data['city']
    state = data['state']
    country = data['country']

    # Redirect link for successful Payment
    surl = 'https://pay-gate1.herokuapp.com/success'

    # Redirect link for Failure Payment
    furl = 'https://pay-gate1.herokuapp.com/failure'

    # service_provider
    service_provider = 'payu_paisa'

    # addres
    zipcode = data['zipcode']

    # for generating txnid
    txnid = generate_txnid()

    # Generating hash
    post_hashseq = f'{merchant_key}|{txnid}|{amount}|{productinfo}|{firstname}|{email}|||||||||||{merchant_salt_v1}'
    # Hash seq should be
    # sha512(key|txnid|amonut|donation|Sameer|sameerborkar79@gmail.com|||||||||||abpR7ROd)sha512(key|txnid|amount|productinfo|firstname|email|||||||||||SALT)

    post_hash = hashlib.sha512(
        post_hashseq.encode("utf-8")).hexdigest().lower()

    dbres = add_db_row(txnid, amount, firstname, email)
    if(type(dbres) == Exception):
        return f'Try Again, {dbres}'

    res_data = {
        'firstname': firstname,
        'lastname': lastname,
        'email': email,
        'phone': int(phone),
        'amount': float(amount),
        'zipcode': zipcode,
        'address1': address1,
        'city': city,
        'state': state,
        'country': country,
        'merchant_key': merchant_key,
        'txnid': txnid,
        'hash': post_hash,
        'productinfo': productinfo,
        'surl': surl,
        'furl': furl

    }

    return jsonify(res_data)


@app.route('/success', methods=['POST'])
def success():

    data = request.values.to_dict(flat=True)

    # verify response hash
    res = verify_resp_hash(data)

    if(type(res) != dict or res['verify'] == 'fail'):
        return render_template('error.html', msg='Transaction Verification Failed')

    change_status(data['txnid'], data['status'], ref_id=data['mihpayid'])

    # Sending mail
    invoice_gen(data['firstname'], data['lastname'], data['email'], data['address1'], data['state'],
                data['country'], data['amount'], data['addedon'], data['status'], data['txnid'])

    return render_template('success_Trans.html', status=data['status'], txnid=data['txnid'], amount=data['amount'], mihpayid=data['mihpayid'])


@app.route('/failure', methods=['POST'])
def failure():

    data = request.values.to_dict(flat=True)

    # verify response hash
    res = verify_resp_hash(data)

    if(type(res) != dict or res['verify'] == 'fail'):
        return render_template('error.html', msg='Transaction Verification Failed')

    change_status(data['txnid'], data['status'], data['mihpayid'])

    # sending invoice
    invoice_gen(data['firstname'], data['lastname'], data['email'], data['address1'], data['state'],
                data['country'], data['amount'], data['addedon'], data['status'], data['txnid'])

    return render_template('failure_Trans.html', status=data['status'], txnid=data['txnid'], amount=data['amount'], mihpayid=data['mihpayid'])


#generate transaction ID
def generate_txnid():
    # for generating txnid
    seq = string.ascii_letters+string.digits
    return "".join(random.choices(seq, k=20))


def verify_resp_hash(data: dict):

    if(type(data) != dict):
        return {'verify': 'fail'}

    resp_amount = data['amount']
    resp_status = data['status']
    resp_txnid = data['txnid']
    resp_hash = data['hash']

    # now we will compare received hash with our data or our calculated hash to verify payment 

    try:
        # retrive data for perticular txnid from database
        db_data = get_db_row(txnid=resp_txnid)[0]

        if(type(db_data) != tuple):
            return
        
        # Hash Generation Logic for Payment Response
        # sha512(SALT|status||||||udf5|udf4|udf3|udf2|udf1|email|firstname|productinfo|amount|txnid|key)
        calc_hashseq = f"{merchant_salt_v1}|{resp_status}|||||||||||{db_data[3]}|{db_data[2]}|donation|{str('{0:.2f}'.format(float(db_data[1])))}|{db_data[0]}|{merchant_key}"

        calc_hash = hashlib.sha512(
            calc_hashseq.encode("utf-8")).hexdigest().lower()
    except :
        return {'verify': 'fail'}
    
    # comparing received hash and calculated hash
    if(calc_hash == resp_hash and resp_amount == str('{0:.2f}'.format(float(db_data[1])))):
        return {'verify': 'pass'}
    else:
        return {'verify': 'fail'}


# fucntion to change status of transaction in database
def change_status(txnid, status, ref_id):
    try:
        query = f"UPDATE transactions_details SET status = '{status}', txn_ref_id= '{ref_id}' WHERE txnid = '{txnid}' ;"

        conn = sql.connect('database/transactions.db')
        conn.execute(query)
        conn.commit()
        conn.close()

        return 'done'
    except:
        return f'{Exception}'



# function to add transaction details
def add_db_row(txnid, amount, firstname, email, status='pending', ref_id='null'):
    try:
        query = f"INSERT INTO transactions_details VALUES ('{txnid}', {amount}, '{firstname}', '{email}', '{status}', '{ref_id}');"

        conn = sql.connect('database/transactions.db')
        conn.execute(query)
        conn.commit()
        conn.close()
        return 'done'

    except Exception as exp:
        
        return exp


# function to retrive transaction details for verification
def get_db_row(txnid: str):

    query = f"SELECT * FROM transactions_details WHERE txnid='{txnid}'"
    conn = sql.connect('database/transactions.db')
    mycur = conn.cursor()
    mycur.execute(query)

    # exmaple of db resp:  [('txnid', 52, 'sameer', 'email', 'status', None)]
    # ie. list of tuples, tuple contain row element
    db_resp = mycur.fetchall()
    conn.close()

    return db_resp


def invoice_gen(firstname, lastname, email, address1, state, country, amount, date, status, txnid):

    #Invoice is in html
    html_temp = render_template(
        'invoices.html',
        firstname=firstname,
        lastname=lastname,
        email=email,
        address1=address1,
        state=state,
        country=country,
        amount=amount,
        date=date,
        status=status,
        txnid=txnid
    )
    
    sendmail(html_temp, receiver = email)


def sendmail(html:str, receiver:str):
    message = Mail(
        from_email=gmail_user,
        to_emails=receiver,
        subject='Payment Invoice',
        html_content=html
        )
    try:
        sg = SendGridAPIClient(os.getenv('sendmail_key',config('sendmail_key')))
        response = sg.send(message)

    except Exception as exp:
        print(exp.message)


# Start point of program
if(__name__ == '__main__'):
    app.run()
