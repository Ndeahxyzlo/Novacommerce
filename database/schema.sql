CREATE TABLE companies (
	id SERIAL NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	slug VARCHAR(170) NOT NULL, 
	description TEXT, 
	email VARCHAR(255), 
	phone VARCHAR(30), 
	city VARCHAR(80), 
	country VARCHAR(80) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	order_seq INTEGER NOT NULL, 
	lead_time_days INTEGER NOT NULL, 
	order_cost NUMERIC(12, 2) NOT NULL, 
	holding_rate NUMERIC(5, 4) NOT NULL, 
	service_level NUMERIC(5, 4) NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_companies_lead_time CHECK (lead_time_days > 0), 
	CONSTRAINT ck_companies_order_cost CHECK (order_cost >= 0), 
	CONSTRAINT ck_companies_holding_rate CHECK (holding_rate > 0 and holding_rate <= 1), 
	CONSTRAINT ck_companies_service_level CHECK (service_level >= 0.5 and service_level < 1), 
	UNIQUE (slug)
);

CREATE TABLE ml_runs (
	id SERIAL NOT NULL, 
	company_id INTEGER, 
	kind VARCHAR(30) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	metrics JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE
);

CREATE INDEX ix_ml_runs_company_id ON ml_runs (company_id);

CREATE TABLE products (
	id SERIAL NOT NULL, 
	company_id INTEGER NOT NULL, 
	sku VARCHAR(60) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description TEXT, 
	category VARCHAR(80) NOT NULL, 
	price NUMERIC(12, 2) NOT NULL, 
	cost NUMERIC(12, 2) NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_products_company_sku UNIQUE (company_id, sku), 
	CONSTRAINT ck_products_price CHECK (price >= 0), 
	CONSTRAINT ck_products_cost CHECK (cost >= 0), 
	FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE
);

CREATE INDEX ix_products_company_category ON products (company_id, category);

CREATE INDEX ix_products_company_id ON products (company_id);

CREATE TABLE users (
	id SERIAL NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	first_name VARCHAR(80) NOT NULL, 
	last_name VARCHAR(80) NOT NULL, 
	phone VARCHAR(30), 
	role VARCHAR(20) NOT NULL, 
	company_id INTEGER, 
	active BOOLEAN NOT NULL, 
	password_changed_at TIMESTAMP WITH TIME ZONE, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_users_role CHECK (role in ('admin', 'owner', 'customer')), 
	CONSTRAINT ck_users_owner_company CHECK (role <> 'owner' or company_id is not null), 
	UNIQUE (email), 
	FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE SET NULL
);

CREATE INDEX ix_users_company_id ON users (company_id);

CREATE TABLE access_logs (
	id BIGSERIAL NOT NULL, 
	user_id INTEGER, 
	email VARCHAR(255), 
	ip VARCHAR(45) NOT NULL, 
	event VARCHAR(30) NOT NULL, 
	success BOOLEAN NOT NULL, 
	path VARCHAR(200), 
	user_agent VARCHAR(255), 
	label INTEGER, 
	risk FLOAT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_access_created ON access_logs (created_at);

CREATE INDEX ix_access_email_created ON access_logs (email, created_at);

CREATE INDEX ix_access_ip_created ON access_logs (ip, created_at);

CREATE TABLE cart_items (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_cart_user_product UNIQUE (user_id, product_id), 
	CONSTRAINT ck_cart_quantity CHECK (quantity > 0 and quantity <= 10000), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);

CREATE TABLE customers (
	id SERIAL NOT NULL, 
	company_id INTEGER NOT NULL, 
	user_id INTEGER, 
	first_name VARCHAR(80) NOT NULL, 
	last_name VARCHAR(80) NOT NULL, 
	email VARCHAR(255), 
	phone VARCHAR(30), 
	city VARCHAR(80), 
	country VARCHAR(80), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_customers_company_email UNIQUE (company_id, email), 
	CONSTRAINT uq_customers_company_user UNIQUE (company_id, user_id), 
	FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_customers_company_id ON customers (company_id);

CREATE TABLE demand_forecasts (
	id SERIAL NOT NULL, 
	company_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	week_start DATE NOT NULL, 
	predicted_units FLOAT NOT NULL, 
	model_kind VARCHAR(30) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_forecast_product_week UNIQUE (product_id, week_start), 
	FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);

CREATE INDEX ix_demand_forecasts_company_id ON demand_forecasts (company_id);

CREATE TABLE inventory (
	id SERIAL NOT NULL, 
	product_id INTEGER NOT NULL, 
	company_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	reorder_point INTEGER NOT NULL, 
	safety_stock INTEGER NOT NULL, 
	eoq INTEGER NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_inventory_quantity CHECK (quantity >= 0), 
	CONSTRAINT ck_inventory_reorder_point CHECK (reorder_point >= 0), 
	CONSTRAINT ck_inventory_safety_stock CHECK (safety_stock >= 0), 
	CONSTRAINT ck_inventory_eoq CHECK (eoq >= 0), 
	UNIQUE (product_id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
	FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE
);

CREATE INDEX ix_inventory_company_id ON inventory (company_id);

CREATE TABLE inventory_movements (
	id BIGSERIAL NOT NULL, 
	company_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	delta INTEGER NOT NULL, 
	reason VARCHAR(30) NOT NULL, 
	reference VARCHAR(60), 
	user_id INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_movements_company_created ON inventory_movements (company_id, created_at);

CREATE INDEX ix_movements_product ON inventory_movements (product_id);

CREATE TABLE wishlists (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_wishlist_user_product UNIQUE (user_id, product_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
);

CREATE TABLE orders (
	id SERIAL NOT NULL, 
	company_id INTEGER NOT NULL, 
	customer_id INTEGER, 
	number INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	channel VARCHAR(20) NOT NULL, 
	total NUMERIC(14, 2) NOT NULL, 
	notes TEXT, 
	created_by INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_orders_company_number UNIQUE (company_id, number), 
	CONSTRAINT ck_orders_status CHECK (status in ('pending', 'paid', 'shipped', 'delivered', 'cancelled')), 
	CONSTRAINT ck_orders_channel CHECK (channel in ('store', 'pos')), 
	CONSTRAINT ck_orders_total CHECK (total >= 0), 
	FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
	FOREIGN KEY(customer_id) REFERENCES customers (id) ON DELETE SET NULL, 
	FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_orders_company_created ON orders (company_id, created_at);

CREATE INDEX ix_orders_customer ON orders (customer_id);

CREATE INDEX ix_orders_updated ON orders (updated_at);

CREATE TABLE order_items (
	id BIGSERIAL NOT NULL, 
	order_id INTEGER NOT NULL, 
	product_id INTEGER, 
	sku VARCHAR(60) NOT NULL, 
	product_name VARCHAR(200) NOT NULL, 
	quantity INTEGER NOT NULL, 
	unit_price NUMERIC(12, 2) NOT NULL, 
	unit_cost NUMERIC(12, 2) NOT NULL, 
	line_total NUMERIC(14, 2) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_order_items_quantity CHECK (quantity > 0), 
	CONSTRAINT ck_order_items_price CHECK (unit_price >= 0), 
	FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE CASCADE, 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE SET NULL
);

CREATE INDEX ix_order_items_order_id ON order_items (order_id);

CREATE INDEX ix_order_items_product ON order_items (product_id);
