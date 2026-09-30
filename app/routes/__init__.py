from . import admin, api, auth, companies, customers, main, orders, products, reports, store

ALL_BLUEPRINTS = [
    main.bp,
    auth.bp,
    store.bp,
    companies.bp,
    products.bp,
    customers.bp,
    orders.bp,
    reports.bp,
    admin.bp,
    api.bp,
]
