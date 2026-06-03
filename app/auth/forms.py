from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, RadioField
from wtforms.validators import DataRequired, Email

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    role = RadioField('Login As', choices=[('admin', 'System Administrator'), ('authority', 'Authority Personnel')], default='authority', validators=[DataRequired()])
    submit = SubmitField('Login to ShellSafe')
