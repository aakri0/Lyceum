-- MySQL dump 10.13  Distrib 9.4.0, for macos26.0 (arm64)
--
-- Host: localhost    Database: ERP
-- ------------------------------------------------------
-- Server version	9.4.0

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Dumping data for table `audit_logs`
--

LOCK TABLES `audit_logs` WRITE;
/*!40000 ALTER TABLE `audit_logs` DISABLE KEYS */;
INSERT INTO `audit_logs` VALUES (1,1,'Test audit log entry','2025-12-29 14:45:58'),(2,10,'Updated grade for enrollment 1','2025-12-30 14:49:18'),(3,10,'Updated grade for enrollment 1','2025-12-30 14:49:21'),(4,10,'Updated grade for enrollment 1','2025-12-30 14:49:30'),(5,10,'Updated grade for enrollment 1','2025-12-30 14:56:38'),(6,10,'Updated grade for enrollment 1','2025-12-30 14:56:40'),(7,10,'Updated grade for enrollment 1','2025-12-30 14:56:42'),(8,10,'Updated grade for enrollment 2','2025-12-30 14:57:10'),(9,10,'Updated grade for enrollment 3','2025-12-30 14:57:56'),(10,10,'Updated grade for enrollment 5','2025-12-31 07:23:27'),(11,10,'Updated grade for enrollment 6','2026-01-07 08:37:45'),(12,10,'Updated grade for enrollment 4','2026-01-31 10:10:01'),(13,10,'Updated grade for enrollment 7','2026-01-31 10:11:15'),(14,10,'Updated grade for enrollment 8','2026-02-02 12:14:22'),(15,10,'Updated grade for enrollment 9','2026-02-02 12:14:49'),(16,10,'Updated grade for enrollment 10','2026-02-02 12:15:20'),(17,10,'Updated grade for enrollment 11','2026-02-02 12:15:45'),(18,10,'Updated grade for enrollment 12','2026-02-02 12:16:10'),(19,10,'Updated grade for enrollment 13','2026-02-02 12:16:39'),(20,10,'Updated grade for enrollment 14','2026-02-02 12:17:12'),(21,10,'Updated grade for enrollment 15','2026-02-02 12:17:37'),(22,10,'Updated grade for enrollment 16','2026-02-02 13:07:55'),(23,10,'Updated grade for enrollment 17','2026-02-02 13:08:08'),(24,10,'Updated grade for enrollment 18','2026-02-02 13:08:19'),(25,10,'Updated grade for enrollment 19','2026-02-02 13:08:28'),(26,10,'Updated grade for enrollment 20','2026-02-02 13:08:45'),(27,10,'Updated grade for enrollment 21','2026-02-02 13:08:57'),(28,10,'Updated grade for enrollment 22','2026-02-02 13:09:09'),(29,10,'Updated grade for enrollment 23','2026-02-02 13:09:17'),(30,10,'Updated grade for enrollment 24','2026-02-02 13:11:10'),(31,10,'Updated grade for enrollment 25','2026-02-02 13:11:20'),(32,10,'Updated grade for enrollment 26','2026-02-02 13:11:34'),(33,10,'Updated grade for enrollment 27','2026-02-02 13:11:43'),(34,10,'Updated grade for enrollment 28','2026-02-02 13:11:50'),(35,10,'Updated grade for enrollment 29','2026-02-02 13:11:57'),(36,10,'Updated grade for enrollment 30','2026-02-02 13:14:42'),(37,10,'Updated grade for enrollment 31','2026-02-02 13:14:52'),(38,10,'Updated grade for enrollment 32','2026-02-02 13:15:00'),(39,10,'Updated grade for enrollment 33','2026-02-02 13:15:38'),(40,10,'Updated grade for enrollment 34','2026-02-02 13:15:46'),(41,10,'Updated grade for enrollment 35','2026-02-02 13:15:57'),(42,10,'Updated grade for enrollment 36','2026-02-02 13:16:06'),(43,10,'Updated grade for enrollment 37','2026-02-02 13:16:13');
/*!40000 ALTER TABLE `audit_logs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `courses`
--

LOCK TABLES `courses` WRITE;
/*!40000 ALTER TABLE `courses` DISABLE KEYS */;
INSERT INTO `courses` VALUES (1,'DATABASE MANAGEMENT SYSTEMS - (THEORY & PRACTICE)',1,4,NULL),(2,'ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING - (THEORY & PRACTICE)',1,4,NULL),(3,'PRINCIPLES OF MANAGEMENT AND ECONOMICS',1,4,NULL),(4,'CLOUD COMPUTING',1,4,NULL),(5,'THEORY OF COMPUTATION',1,4,NULL),(6,'Test',1,3,NULL),(7,'FUNDAMENTALS OF LINEAR ALGEBRA, CALCULUS AND STATISTICS',1,4,NULL),(8,'CHEMISTRY OF SMART MATERIALS AND DEVICES - (THEORY & PRACTICE)',1,4,NULL),(9,'COMPUTER AIDED ENGINEERING GRAPHICS',1,3,NULL),(10,'FUNDAMENTALS OF MECHANICAL ENGINEERING',1,3,NULL),(11,'INTRODUCTION TO PYTHON PROGRAMMING - (THEORY & PRACTICE)',1,3,NULL),(12,'COMMUNICATIVE ENGLISH-I',1,1,NULL),(13,'FUNDAMENTALS OF INDIAN CONSTITUTION',1,1,NULL),(14,'SCIENTIFIC FOUNDATIONS OF HEALTH-YOGA PRACTICE',1,1,NULL),(15,'NUMBER THEORY, VECTOR CALCULUS AND COMPUTATIONAL METHODS',1,4,NULL),(16,'QUANTUM PHYSICS FOR ENGINEERS - (THEORY & PRACTICE)',1,4,NULL),(17,'INTRODUCTION TO CYBER SECURITY',1,3,NULL),(18,'COMMUNICATIVE ENGLISH-II',1,1,NULL),(19,'BALAKE KANNADA',1,1,NULL),(20,'ELEMENTS OF CIVIL ENGINEERING',1,3,NULL),(21,'IDEA LAB',1,1,NULL),(22,'PRINCIPLES OF PROGRAMMING USING C - (THEORY & PRACTICE)',1,3,NULL),(23,'DESIGN THINKING LAB',1,2,NULL),(24,'OPERATING SYSTEMS - (THEORY & PRACTICE)',1,4,NULL),(25,'LOGIC DESIGN AND COMPUTER ORGANISATION',1,4,NULL),(26,'DATA STRUCTURE AND APPLICATIONS - (THEORY & PRACTICE)',1,4,NULL),(27,'BIO SAFETY STANDARDS AND ETHICS',1,3,NULL),(28,'LINEAR ALGEBRA AND PROBABILITY THEORY',1,4,NULL),(29,'DISCRETE MATHEMATICAL STRUCTURES AND COMBINATORICS',1,3,NULL),(30,'ENVIRONMENT AND SUSTAINABILTY',1,3,NULL),(31,'DESIGN AND ANALYSIS OF ALGORITHMS - (THEORY & PRACTICE)',1,4,NULL),(32,'INTERNET OF THINGS AND APPLICATIONS - (THEORY & PRACTICE)',1,4,NULL),(33,'COMPUTER NETWORKS',1,3,NULL),(34,'DATA SCIENCE FOR ENGINEERS - (MOOC)',1,2,NULL),(35,'PHYSICAL EDUCATION : SPORTS AND ATHLETICS',1,2,NULL),(36,'UNIVERSAL HUMAN VALUES',1,2,NULL);
/*!40000 ALTER TABLE `courses` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `departments`
--

LOCK TABLES `departments` WRITE;
/*!40000 ALTER TABLE `departments` DISABLE KEYS */;
INSERT INTO `departments` VALUES (1,'Information Science and Engineering');
/*!40000 ALTER TABLE `departments` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `documents`
--

LOCK TABLES `documents` WRITE;
/*!40000 ALTER TABLE `documents` DISABLE KEYS */;
/*!40000 ALTER TABLE `documents` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `enrollments`
--

LOCK TABLES `enrollments` WRITE;
/*!40000 ALTER TABLE `enrollments` DISABLE KEYS */;
INSERT INTO `enrollments` VALUES (1,1,1,5,'9',NULL),(2,5,1,5,'8',NULL),(3,1,2,5,'8',NULL),(4,2,2,5,'9',NULL),(5,2,1,5,'10',NULL),(6,1,6,5,'9',NULL),(7,5,5,5,'8',NULL),(8,1,7,1,'10',NULL),(9,1,8,1,'10',NULL),(10,1,9,1,'8',NULL),(11,1,10,1,'9',NULL),(12,1,11,1,'10',NULL),(13,1,12,1,'9',NULL),(14,1,13,1,'8',NULL),(15,1,14,1,'6',NULL),(16,1,15,2,'9',NULL),(17,1,16,2,'9',NULL),(18,1,17,2,'9',NULL),(19,1,18,2,'9',NULL),(20,1,19,2,'7',NULL),(21,1,20,2,'9',NULL),(22,1,21,2,'9',NULL),(23,1,22,2,'9',NULL),(24,1,23,3,'9',NULL),(25,1,24,3,'8',NULL),(26,1,25,3,'7',NULL),(27,1,26,3,'9',NULL),(28,1,27,3,'8',NULL),(29,1,28,3,'8',NULL),(30,1,29,4,'9',NULL),(31,1,30,4,'8',NULL),(32,1,31,4,'8',NULL),(33,1,32,4,'9',NULL),(34,1,33,4,'8',NULL),(35,1,34,4,'9',NULL),(36,1,35,4,'9',NULL),(37,1,36,4,'8',NULL);
/*!40000 ALTER TABLE `enrollments` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `faculty`
--

LOCK TABLES `faculty` WRITE;
/*!40000 ALTER TABLE `faculty` DISABLE KEYS */;
INSERT INTO `faculty` VALUES (1,3,1),(2,10,1);
/*!40000 ALTER TABLE `faculty` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `grade_components`
--

LOCK TABLES `grade_components` WRITE;
/*!40000 ALTER TABLE `grade_components` DISABLE KEYS */;
/*!40000 ALTER TABLE `grade_components` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `otp_verification`
--

LOCK TABLES `otp_verification` WRITE;
/*!40000 ALTER TABLE `otp_verification` DISABLE KEYS */;
INSERT INTO `otp_verification` VALUES (8,'617051','2025-12-29 02:29:43'),(2,'150331','2025-12-31 12:56:39');
/*!40000 ALTER TABLE `otp_verification` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `password_resets`
--

LOCK TABLES `password_resets` WRITE;
/*!40000 ALTER TABLE `password_resets` DISABLE KEYS */;
INSERT INTO `password_resets` VALUES (1,'6b74a159-4c42-46d8-ad04-97b4f88d50da','2026-02-02 17:49:51');
/*!40000 ALTER TABLE `password_resets` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `students`
--

LOCK TABLES `students` WRITE;
/*!40000 ALTER TABLE `students` DISABLE KEYS */;
INSERT INTO `students` VALUES (1,1,'1RV23IS003',1,3),(2,2,'1RV23IS004',1,3),(4,8,'1RV23IS005',1,3),(5,9,'1RV23IS020',1,3),(6,12,'1RV23IS062',1,3);
/*!40000 ALTER TABLE `students` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `swd_requests`
--

LOCK TABLES `swd_requests` WRITE;
/*!40000 ALTER TABLE `swd_requests` DISABLE KEYS */;
INSERT INTO `swd_requests` VALUES (1,1,'Hostel','Room C-312 the tubelight has stopped working.','approved','2026-02-02 12:19:01',NULL,NULL),(2,1,'Hostel','The fan in room C-312 has stopped working','pending','2026-02-02 12:35:56',NULL,2);
/*!40000 ALTER TABLE `swd_requests` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (1,'Aakrisht Tiwary','aakrishttiwary.is23@rvce.edu.in','$2b$12$NdKtvidsQjCa8/inen3fm.jZ8n.k7QwPlRL1.ZjajWmh/qCmo1Nr2','student',0),(2,'Aayush Pandey','aayushpandey.is23@rvce.edu.in','$2b$12$x9rY321WSUI2P8iUvxPlJe.TdtONk.s5yD2W1taWDSpdIpnDTI.36','student',0),(3,'Padmashree T','padmashreet@rvce.edu.in','$2b$12$3BwVYesFYjBXoZOFaE5.c.uyTHJ.sNO1XsdGbyyVkbISszJ8GlXW.','faculty',1),(4,'admin','5080340.olympiad.10.aakr@gmail.com','$2b$12$LBD9AVNM/8lXm6WHjP0qGu5zsVRs5heO1vLauJb1CTKrmgCH.MA.u','admin',0),(8,'Kartthik','kartthik1811@gmail.com','$2b$12$.kIg.gNJigm6JLlV2rYmEedwTGr1q5Ta.3UOJg4sOP5nKwVI1863q','student',0),(9,'Anurag Rath','anuragrath.is23@rvce.edu.in','$2b$12$cFL6Jlcg4/PpEJfMBSI6Yuckx7IW9pv1psFEaW8klo2EnhVxf2Jde','student',0),(10,'Faculty','dazisht@gmail.com','$2b$12$7oBSEvRpvOuIOaubWTqkl.sBof7FuPwbQ3JeP8k39klp8lLuotABy','faculty',0),(12,'Kotra Ssank','kotrasasank.is23@rvce.edu.in','$2b$12$pMwx/NSNy9Zh8JxU/A6X.u5Z.PQwhZpGJEGHlYByUhKeiWgewAYea','student',1);
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-02-02 20:32:45
