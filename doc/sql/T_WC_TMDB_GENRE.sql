-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Hôte : mariadb
-- Généré le : dim. 03 mai 2026 à 07:16
-- Version du serveur : 11.2.3-MariaDB
-- Version de PHP : 8.2.16

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Base de données : `vaugouindb`
--

-- --------------------------------------------------------

--
-- Structure de la table `T_WC_TMDB_GENRE`
--

CREATE TABLE `T_WC_TMDB_GENRE` (
  `id` int(11) NOT NULL,
  `name` varchar(250) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `T_WC_TMDB_GENRE`
--

INSERT INTO `T_WC_TMDB_GENRE` (`id`, `name`) VALUES
(28, 'Action'),
(10759, 'Action & Adventure'),
(12, 'Adventure'),
(16, 'Animation'),
(35, 'Comedy'),
(80, 'Crime'),
(99, 'Documentary'),
(18, 'Drama'),
(10751, 'Family'),
(14, 'Fantasy'),
(36, 'History'),
(27, 'Horror'),
(10762, 'Kids'),
(10402, 'Music'),
(9648, 'Mystery'),
(10763, 'News'),
(10764, 'Reality'),
(10749, 'Romance'),
(10765, 'Sci-Fi & Fantasy'),
(878, 'Science Fiction'),
(10766, 'Soap'),
(10767, 'Talk'),
(53, 'Thriller'),
(10770, 'TV Movie'),
(10752, 'War'),
(10768, 'War & Politics'),
(37, 'Western');

-- --------------------------------------------------------

--
-- Structure de la table `T_WC_TMDB_GENRE_LANG`
--

CREATE TABLE `T_WC_TMDB_GENRE_LANG` (
  `ID_ROW` int(11) NOT NULL,
  `id` int(11) NOT NULL,
  `LANG` varchar(10) DEFAULT NULL,
  `name` varchar(250) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Déchargement des données de la table `T_WC_TMDB_GENRE_LANG`
--

INSERT INTO `T_WC_TMDB_GENRE_LANG` (`ID_ROW`, `id`, `LANG`, `name`) VALUES
(1, 28, 'fr', 'Action'),
(2, 12, 'fr', 'Aventure'),
(3, 16, 'fr', 'Animation'),
(4, 35, 'fr', 'Comédie'),
(5, 80, 'fr', 'Crime'),
(6, 99, 'fr', 'Documentaire'),
(7, 18, 'fr', 'Drame'),
(8, 10751, 'fr', 'Familial'),
(9, 14, 'fr', 'Fantastique'),
(10, 36, 'fr', 'Histoire'),
(11, 27, 'fr', 'Horreur'),
(12, 10402, 'fr', 'Musique'),
(13, 9648, 'fr', 'Mystère'),
(14, 10749, 'fr', 'Romance'),
(15, 878, 'fr', 'Science-Fiction'),
(16, 53, 'fr', 'Thriller'),
(17, 10770, 'fr', 'Téléfilm'),
(18, 10752, 'fr', 'Guerre'),
(19, 37, 'fr', 'Western');

--
-- Index pour les tables déchargées
--

--
-- Index pour la table `T_WC_TMDB_GENRE`
--
ALTER TABLE `T_WC_TMDB_GENRE`
  ADD PRIMARY KEY (`id`),
  ADD KEY `name` (`name`);

--
-- Index pour la table `T_WC_TMDB_GENRE_LANG`
--
ALTER TABLE `T_WC_TMDB_GENRE_LANG`
  ADD PRIMARY KEY (`ID_ROW`),
  ADD KEY `id` (`id`),
  ADD KEY `LANG` (`LANG`),
  ADD KEY `name` (`name`);

--
-- AUTO_INCREMENT pour les tables déchargées
--

--
-- AUTO_INCREMENT pour la table `T_WC_TMDB_GENRE_LANG`
--
ALTER TABLE `T_WC_TMDB_GENRE_LANG`
  MODIFY `ID_ROW` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=20;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
