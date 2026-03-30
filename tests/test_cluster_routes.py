from app.models.cluster import Cluster, ClusterAccount, AccountPost, Platform
from app.models.clip import Clip
from app.models.clip_extraction import ClipExtraction, ExtractionStatus
from app.models.user import User
from app.services.auth import create_access_token


def _create_user(db, credits=10):
    user = User(email="test@example.com", password_hash="hashed", credits_remaining=credits)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_header(user_id: str) -> dict:
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}


class TestCreateCluster:
    def test_create_cluster(self, client, db):
        user = _create_user(db)
        resp = client.post("/clusters", json={"name": "Charlie Morgan Minecraft"}, headers=_auth_header(user.id))
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Charlie Morgan Minecraft"
        assert data["accounts"] == []
        assert data["extractions"] == []

    def test_create_cluster_unauthenticated(self, client, db):
        resp = client.post("/clusters", json={"name": "Test"})
        assert resp.status_code == 403


class TestListClusters:
    def test_list_empty(self, client, db):
        user = _create_user(db)
        resp = client.get("/clusters", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert resp.json()["clusters"] == []

    def test_list_with_clusters(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Test Cluster")
        db.add(cluster)
        db.commit()
        resp = client.get("/clusters", headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert len(resp.json()["clusters"]) == 1
        assert resp.json()["clusters"][0]["name"] == "Test Cluster"
        assert resp.json()["clusters"][0]["account_count"] == 0


class TestGetCluster:
    def test_get_cluster_detail(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Detail Test")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        resp = client.get(f"/clusters/{cluster.id}", headers=_auth_header(user.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Detail Test"
        assert data["accounts"] == []

    def test_get_nonexistent(self, client, db):
        user = _create_user(db)
        resp = client.get("/clusters/nonexistent", headers=_auth_header(user.id))
        assert resp.status_code == 404


class TestUpdateCluster:
    def test_update_name(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Old Name")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        resp = client.put(f"/clusters/{cluster.id}", json={"name": "New Name"}, headers=_auth_header(user.id))
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"


class TestDeleteCluster:
    def test_delete_cluster(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="To Delete")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        cluster_id = cluster.id
        resp = client.delete(f"/clusters/{cluster_id}", headers=_auth_header(user.id))
        assert resp.status_code == 204
        db.expire_all()
        assert db.query(Cluster).filter(Cluster.id == cluster_id).first() is None

    def test_delete_unlinks_extractions(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Unlink Test")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        extraction = ClipExtraction(
            user_id=user.id,
            youtube_url="https://youtube.com/watch?v=abc",
            cluster_id=cluster.id,
        )
        db.add(extraction)
        db.commit()
        db.refresh(extraction)
        ext_id = extraction.id
        client.delete(f"/clusters/{cluster.id}", headers=_auth_header(user.id))
        db.expire_all()
        ext = db.query(ClipExtraction).filter(ClipExtraction.id == ext_id).first()
        assert ext is not None
        assert ext.cluster_id is None


class TestAddAccount:
    def test_add_account(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Acc Test")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        resp = client.post(
            f"/clusters/{cluster.id}/accounts",
            json={"platform": "tiktok", "handle": "@charlie"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 201
        assert resp.json()["platform"] == "tiktok"
        assert resp.json()["handle"] == "@charlie"

    def test_add_duplicate_account(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Dup Test")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        client.post(
            f"/clusters/{cluster.id}/accounts",
            json={"platform": "tiktok", "handle": "@charlie"},
            headers=_auth_header(user.id),
        )
        resp = client.post(
            f"/clusters/{cluster.id}/accounts",
            json={"platform": "tiktok", "handle": "@charlie"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 409

    def test_invalid_platform(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Invalid Plat")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        resp = client.post(
            f"/clusters/{cluster.id}/accounts",
            json={"platform": "myspace", "handle": "@tom"},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 422


class TestRemoveAccount:
    def test_remove_account(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Remove Test")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        account = ClusterAccount(cluster_id=cluster.id, platform=Platform.youtube, handle="@test")
        db.add(account)
        db.commit()
        db.refresh(account)
        resp = client.delete(f"/clusters/{cluster.id}/accounts/{account.id}", headers=_auth_header(user.id))
        assert resp.status_code == 204


class TestPosts:
    def test_create_post(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Post Test")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        account = ClusterAccount(cluster_id=cluster.id, platform=Platform.tiktok, handle="@post")
        db.add(account)
        db.commit()
        db.refresh(account)
        resp = client.post(
            f"/clusters/{cluster.id}/accounts/{account.id}/posts",
            json={"views": 1000, "likes": 50},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 201
        assert resp.json()["views"] == 1000
        assert resp.json()["likes"] == 50

    def test_update_post(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Update Post")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        account = ClusterAccount(cluster_id=cluster.id, platform=Platform.tiktok, handle="@upd")
        db.add(account)
        db.commit()
        db.refresh(account)
        post = AccountPost(account_id=account.id, views=100, likes=10, comments=5, shares=2)
        db.add(post)
        db.commit()
        db.refresh(post)
        resp = client.put(
            f"/clusters/{cluster.id}/accounts/{account.id}/posts/{post.id}",
            json={"views": 5000},
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200
        assert resp.json()["views"] == 5000
        assert resp.json()["likes"] == 10  # unchanged

    def test_delete_post(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Del Post")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        account = ClusterAccount(cluster_id=cluster.id, platform=Platform.tiktok, handle="@del")
        db.add(account)
        db.commit()
        db.refresh(account)
        post = AccountPost(account_id=account.id, views=100, likes=10, comments=5, shares=2)
        db.add(post)
        db.commit()
        db.refresh(post)
        resp = client.delete(
            f"/clusters/{cluster.id}/accounts/{account.id}/posts/{post.id}",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 204

    def test_cluster_stats_aggregate(self, client, db):
        user = _create_user(db)
        cluster = Cluster(name="Stats Test")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        acc1 = ClusterAccount(cluster_id=cluster.id, platform=Platform.tiktok, handle="@s1")
        acc2 = ClusterAccount(cluster_id=cluster.id, platform=Platform.youtube, handle="@s2")
        db.add_all([acc1, acc2])
        db.commit()
        db.refresh(acc1)
        db.refresh(acc2)
        db.add(AccountPost(account_id=acc1.id, views=1000, likes=100, comments=10, shares=5))
        db.add(AccountPost(account_id=acc2.id, views=2000, likes=200, comments=20, shares=10))
        db.commit()
        resp = client.get(f"/clusters/{cluster.id}", headers=_auth_header(user.id))
        data = resp.json()
        assert data["stats"]["views"] == 3000
        assert data["stats"]["likes"] == 300
        assert data["accounts"][0]["stats"]["views"] in [1000, 2000]


class TestExtractionWithCluster:
    def test_extraction_shows_in_cluster(self, client, db):
        from unittest.mock import patch
        user = _create_user(db)
        cluster = Cluster(name="Ext Test")
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        with patch("app.routes.clips._dispatch_extraction"):
            resp = client.post(
                "/clips/extract",
                json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "cluster_id": cluster.id},
                headers=_auth_header(user.id),
            )
        assert resp.status_code == 201
        detail = client.get(f"/clusters/{cluster.id}", headers=_auth_header(user.id))
        assert len(detail.json()["extractions"]) == 1
