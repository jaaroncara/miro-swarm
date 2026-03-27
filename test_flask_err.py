from flask import Flask, jsonify
import openai

app = Flask(__name__)

@app.route("/")
def index():
    raise openai.BadRequestError("test", response=None, body=None)

@app.errorhandler(Exception)
def handle_err(e):
    return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    with app.test_client() as client:
        res = client.get("/")
        print("Status code:", res.status_code)
