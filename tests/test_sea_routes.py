from fastapi.testclient import TestClient
from sherlock.api.app import app


def test_ocean_route_has_intermediate_waypoints():
    client = TestClient(app)
    response = client.get('/sea-route', params=dict(lon1=22.926, lat1=40.635, lon2=-118.26, lat2=33.73))
    assert response.status_code == 200
    data = response.json()
    assert data['estimated'] is True
    assert data['geometry']['type'] == 'LineString'
    assert len(data['geometry']['coordinates']) > 20
    assert client.get('/sea-route', params=dict(lon1=999, lat1=40, lon2=0, lat2=0)).status_code == 422
