from flask import abort, current_app, request
from flask_login import current_user
from flask_sqlalchemy.pagination import SelectPagination
from sqlalchemy import select

from ..extensions import db


def scoped_get_or_404(model, object_id):
    found = db.session.scalar(
        select(model).where(model.id == object_id, model.company_id == current_user.company_id)
    )
    if found is None:
        abort(404)
    return found


class RowPagination(SelectPagination):
    def _query_items(self):
        query = self._query_args["select"].limit(self.per_page).offset(self._query_offset)
        return list(self._query_args["session"].execute(query).unique().all())


def paginate(query):
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = current_app.config["ITEMS_PER_PAGE"]
    if len(query.column_descriptions) == 1:
        return db.paginate(query, page=page, per_page=per_page, error_out=False)
    return RowPagination(page=page, per_page=per_page, max_per_page=None, error_out=False, count=True, select=query, session=db.session())
