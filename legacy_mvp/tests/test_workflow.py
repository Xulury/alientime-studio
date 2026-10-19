import io, os, tempfile
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient

os.environ['STUDIO_DATA_DIR']=tempfile.mkdtemp()
from app.main import app,connect
client=TestClient(app)

def test_end_to_end_local():
    res=client.post('/watches',data={'sku':'AT001','brand':'Richard Mille','model':'RM 67-01'},follow_redirects=False)
    assert res.status_code==303
    wid=res.headers['location'].split('/')[2].split('?')[0]
    im=Image.new('RGB',(320,240),'white'); f=io.BytesIO();im.save(f,'JPEG')
    r=client.post(f'/watches/{wid}/images',files=[('files',('watch.jpg',f.getvalue(),'image/jpeg'))],follow_redirects=False)
    assert r.status_code==303
    assert client.post(f'/watches/{wid}/drafts',follow_redirects=False).status_code==303
    assert client.post(f'/watches/{wid}/approve',data={'confirm':'yes'},follow_redirects=False).status_code==303
    with connect() as c:
        w=c.execute('SELECT * FROM watches WHERE id=?',(wid,)).fetchone()
        assert w['approved_revision']==w['revision']
    assert client.get(f'/watches/{wid}/export').status_code==200
    assert client.post(f'/watches/{wid}/lifecycle',data={'status':'sold'},follow_redirects=False).status_code==303
    assert client.get('/health').json()['publishing']=='disabled'

def test_no_unapproved_publish_routes():
    assert client.post('/publish').status_code==404

def test_publication_connector_fails_closed():
    from app.integrations.contracts import DisabledPublisher,IntegrationNotConfigured,ListingPackage
    import pytest
    with pytest.raises(IntegrationNotConfigured):
        DisabledPublisher('shopify').publish(ListingPackage('test',1,'shopify','draft',()))

def test_dashboard_html():
    r=client.get('/')
    assert r.status_code==200
    assert 'ALIEN TIME' in r.text
