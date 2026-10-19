-- 로컬 개발용 DB/계정 생성 (postgres 슈퍼유저로 1회 실행)
--   psql -h localhost -U postgres -v db_password=<원하는 비밀번호> -f backend/db/init.sql
-- 같은 비밀번호를 backend/src/main/resources/application-local.yml (또는 환경변수 DB_PASSWORD) 에 넣는다.
-- 테이블은 애플리케이션 기동 시 Flyway 가 생성한다 (backend/src/main/resources/db/migration).
CREATE ROLE factory LOGIN PASSWORD :'db_password';
CREATE DATABASE factory_demo OWNER factory ENCODING 'UTF8';
