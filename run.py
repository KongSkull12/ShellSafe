from app import create_app

app = create_app()

if __name__ == '__main__':
    # Local dev runner only; Vercel/gunicorn import `app` and never hit this.
    app.config['ENV'] = 'development'
    app.run(debug=True)
