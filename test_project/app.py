# app.py
from flask import Flask, request, jsonify

todos = []

app = Flask(__name__)

@app.route('/todos', methods=['GET'])
def get_todos():
    return jsonify(todos)

@app.route('/todos', methods=['POST'])
def create_todo():
    todo = request.json.get('todo')
    todos.append(todo)
    return jsonify({'message': 'Todo created successfully'}), 201

@app.route('/todos/<int:todo_id>', methods=['GET'])
def get_todo(todo_id):
    if todo_id < len(todos):
        return jsonify(todos[todo_id])
    else:
        return jsonify({'message': 'Todo not found'}), 404

@app.route('/todos/<int:todo_id>', methods=['DELETE'])
def delete_todo(todo_id):
    if todo_id < len(todos):
        del todos[todo_id]
        return jsonify({'message': 'Todo deleted successfully'})
    else:
        return jsonify({'message': 'Todo not found'}), 404

if __name__ == '__main__':
    app.run(debug=True)
