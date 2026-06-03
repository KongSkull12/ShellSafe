from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user
from app.auth import bp
from app.auth.forms import LoginForm
from app.models import User
from werkzeug.urls import url_parse

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('main.admin_dashboard'))
        else:
            return redirect(url_for('main.authority_dashboard'))
            
    form = LoginForm()
    if form.validate_on_submit():
        # Query Firestore for user by email
        user = User.get_by_email(form.email.data)
        
        if user is None or not user.check_password(form.password.data):
            flash('Invalid email or password')
            return redirect(url_for('auth.login'))
        
        if user.role != form.role.data:
            flash('Selected role does not match account privileges.')
            return redirect(url_for('auth.login'))

        login_user(user, remember=form.remember_me.data)
        
        if user.role == 'admin':
            return redirect(url_for('main.admin_dashboard'))
        else:
            return redirect(url_for('main.authority_dashboard'))
            
    return render_template('auth/login.html', title='Sign In', form=form)

@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))

