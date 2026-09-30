do $do$
begin
    if not exists (select 1 from pg_roles where rolname = 'dw_reader') then
        create role dw_reader nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'dw_etl') then
        create role dw_etl nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'dw_auditor') then
        create role dw_auditor nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'bi_reader') then
        create role bi_reader login;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'auditor_dw') then
        create role auditor_dw login;
    end if;
end
$do$;

select format('alter role bi_reader with password %L', :'bi_password') \gexec
select format('alter role auditor_dw with password %L', :'auditor_password') \gexec

grant dw_reader to bi_reader;
grant dw_auditor to auditor_dw;
alter role bi_reader set statement_timeout = '60s';
alter role bi_reader connection limit 10;
alter role auditor_dw connection limit 3;

do $do$
begin
    execute format('grant connect on database %I to bi_reader, auditor_dw', current_database());
    if exists (select 1 from pg_roles where rolname = 'novacommerce') then
        grant dw_reader, dw_etl, dw_auditor to novacommerce;
    end if;
end
$do$;
