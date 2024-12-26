from flask import current_app, render_template
from flask_login import login_required

from app import tasks
from app.auth import role_required
from app.main import bp


@bp.route('/load_card_data', methods=['GET'])
@role_required('admin')
@login_required
def load_card_data():
    current_app.task_queue.enqueue(tasks.get_card_data)

    return render_template('index.html')




